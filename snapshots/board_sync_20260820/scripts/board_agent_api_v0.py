#!/usr/bin/env python3
"""开发板侧最小 Agent HTTP API。

本文件用于验证 MVP 第一阶段的 PC—开发板应用层通信，并封装当前板端 Harness
会议处理链路。服务仍然只使用 Python 标准库，不引入 FastAPI、Flask 等额外依赖。

当前控制面接口：

    GET  /v1/health
    POST /v1/tasks
    GET  /v1/tasks/{task_id}
    POST /v1/tasks/{task_id}/cancel
    GET  /v1/tasks/{task_id}/result

当前数据面接口：

    PUT  /v1/tasks/{task_id}/audio

当前支持的任务类型：

    transport_probe
        验证任务创建、异步状态变化和查询，不接收音频。

    audio_upload_probe
        等待 PC 上传一个 WAV，流式写入临时文件并校验大小和 SHA-256。
        上传校验成功后的 ``completed`` 只表示“上传探针完成”，不表示 NPU
        或会议纪要处理完成。

    harness_meeting_v0
        上传校验成功后，在板端后台运行现有 Harness，依次执行 3D-Speaker 分段、
        Batch ASR、转写准备、Qwen3-4B 16K 摘要和兼容产物导出。
        只有 ``stage=meeting_ready`` 才表示会议结果已经生成。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from board_harness_worker_v0 import (
    HARNESS_MODEL_PROFILE as WORKER_HARNESS_MODEL_PROFILE,
    HarnessRunConfig,
    HarnessWorkerCancelled,
    HarnessWorkerError,
    run_harness_task,
)


# ---------------------------------------------------------------------------
# 服务配置
# ---------------------------------------------------------------------------

# 监听 0.0.0.0，表示允许同一局域网内的 PC 访问。
# 如果只监听 127.0.0.1，只有开发板自身能够访问，PC 将无法连接。
DEFAULT_HOST = "0.0.0.0"

# 这是 Agent API 的端口，不是内部 rkllm3-server 使用的模型服务端口。
DEFAULT_PORT = 18080

# 上传探针的临时工作目录。真实会议任务接入后，应改为正式的加密工作区。
DEFAULT_DATA_ROOT = Path("/userdata/meeting_agent/runtime/board_agent_api_v0")

# 每次从 HTTP 请求读取 1 MiB，避免将整个 WAV 载入内存。
UPLOAD_CHUNK_BYTES = 1024 * 1024

# 当前探针的保护上限。它不是 PRD 中 120 分钟的性能承诺，也不替代 WAV 时长校验。
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024

# 上传接口允许的 MIME 类型。application/octet-stream 用于兼容部分 PC 客户端。
AUDIO_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "application/octet-stream",
}

# 协议和 Agent 版本先作为响应元数据返回，后续 PC Gateway 可以据此做兼容性检查。
PROTOCOL_VERSION = "board-agent.v1"
AGENT_VERSION = "0.2.0"

# 当前服务实际执行 Harness 时使用的模型配置。此前失败的 Qwen3-8B 不再作为
# 服务默认模型，也不应在健康接口中继续伪装成当前可用的会议处理配置。
MODEL_PROFILE = "qwen3-4b-v104-ctx16k"

# Harness 本轮固定沿用当前已验证的 Qwen3-4B 16K 配置。
HARNESS_TASK_KIND = "harness_meeting_v0"
HARNESS_MODEL_PROFILE = WORKER_HARNESS_MODEL_PROFILE
MAX_RESULT_BYTES = 8 * 1024 * 1024

# 终止状态下允许创建新的任务。MVP 当前只允许一个活动任务。
TERMINAL_STATES = {"completed", "cancelled", "failed"}


# 当前版本只在内存中保存一个任务。
# 后续接入真实会议处理后，需要将任务状态和审计事件持久化到本地工作区。
_task: dict[str, object] | None = None

# HTTP 服务使用多线程处理请求，因此修改全局任务状态时必须加锁。
_task_lock = threading.Lock()

# 当前只有一个活动任务，因此只需要保存一个 Harness 取消事件。取消请求设置
# 该事件，Worker 会终止正在运行的 Harness 子进程并保持 cancelled 状态。
_harness_cancel_event: threading.Event | None = None


class UploadError(Exception):
    """表示上传请求可预期的格式、大小或完整性错误。"""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# 通用工具函数
# ---------------------------------------------------------------------------


def utc_now() -> str:
    """返回 UTC ISO-8601 时间字符串，便于 PC 端显示和审计记录。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    """发送 JSON 响应。

    当前控制面请求都使用短连接，响应完成后主动关闭连接。后续如果增加 SSE，
    SSE 将使用独立的长连接处理，不复用本函数。
    """

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()

    # 如果 PC 在服务端写响应前已经关闭请求，wfile.write() 可能产生
    # BrokenPipeError。此时只结束当前请求，不能让整个 Agent 服务退出。
    try:
        handler.wfile.write(body)
    except BrokenPipeError:
        pass


def send_error_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    code: str,
    message: str,
) -> None:
    """按统一结构返回错误，方便 PC Gateway 根据 error.code 处理。"""

    send_json(
        handler,
        status,
        {
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    """读取小型 JSON 控制请求。

    当前函数只用于任务创建等控制面请求，不用于音频上传。WAV 上传使用独立的
    二进制流处理逻辑，避免把大文件读取到 JSON 或内存中。
    """

    raw_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Content-Length must be an integer") from exc

    # 控制面请求只允许较小的 JSON，防止错误客户端发送超大请求。
    if length < 0 or length > 64 * 1024:
        raise ValueError("request body is too large")

    raw_body = handler.rfile.read(length)
    if not raw_body:
        return {}

    value = json.loads(raw_body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


def task_snapshot() -> dict[str, object] | None:
    """返回当前任务的快照，不把可变全局对象直接交给响应逻辑。"""

    with _task_lock:
        if _task is None:
            return None
        snapshot = dict(_task)
        for key in ("error", "harness_stage_details", "artifact_refs"):
            value = _task.get(key)
            if isinstance(value, dict):
                snapshot[key] = dict(value)
        return snapshot


def task_directory(task_id: str) -> Path:
    """返回一个任务专属目录。

    task_id 由本服务使用 UUID 生成，不接受 PC 自定义路径，因此不会把请求内容
    直接拼接成任意文件路径。
    """

    return DEFAULT_DATA_ROOT / task_id


def harness_directory(task_id: str) -> Path:
    """返回当前 Harness 任务的独立输出目录。"""

    return task_directory(task_id) / "harness"


def remove_task_files(task_id: str) -> None:
    """清理上传探针的临时目录。

    当前目录根路径固定为 DEFAULT_DATA_ROOT，且 task_id 由服务端生成。后续如果
    支持更复杂的 DataObject 生命周期，需要把删除结果写入审计事件。
    """

    directory = task_directory(task_id)
    shutil.rmtree(directory, ignore_errors=True)


def mark_task_failed(task_id: str, code: str, message: str) -> dict[str, object] | None:
    """将当前任务标记为失败，并返回失败状态快照。"""

    global _task

    with _task_lock:
        if _task is None or _task["task_id"] != task_id:
            return None

        # 已取消的任务保持 cancelled，不被上传异常覆盖成 failed。
        if _task["state"] != "cancelled":
            _task["state"] = "failed"
            _task["stage"] = "audio_upload"
            _task["seq"] = int(_task["seq"]) + 1
            _task["updated_at"] = utc_now()
            _task["error"] = {
                "code": code,
                "message": message,
            }
        return dict(_task)


def advance_task(task_id: str, state: str, stage: str) -> bool:
    """推进任务状态。

    如果任务不存在、task_id 不匹配，或者任务已经被取消／完成，则不再推进。
    这样可以防止取消请求之后，后台线程又把任务改回 completed。
    """

    global _task

    with _task_lock:
        if _task is None or _task["task_id"] != task_id:
            return False
        if _task["state"] in TERMINAL_STATES:
            return False

        _task["state"] = state
        _task["stage"] = stage
        _task["seq"] = int(_task["seq"]) + 1
        _task["updated_at"] = utc_now()
        return True


def _safe_stage_details(details: dict[str, object]) -> dict[str, object]:
    """Keep only small JSON-safe stage details in the task snapshot."""

    allowed = {"status", "return_code", "elapsed_seconds", "log", "error"}
    result: dict[str, object] = {}
    for key in allowed:
        value = details.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


def update_harness_stage(
    task_id: str,
    stage: str,
    details: dict[str, object],
) -> bool:
    """Publish one Harness stage without allowing a cancelled task to revive."""

    global _task

    with _task_lock:
        if _task is None or _task["task_id"] != task_id:
            return False
        if _task["state"] in TERMINAL_STATES:
            return False
        _task["state"] = "processing"
        _task["stage"] = stage
        _task["harness_stage_details"] = _safe_stage_details(details)
        _task["seq"] = int(_task["seq"]) + 1
        _task["updated_at"] = utc_now()
        return True


def mark_harness_failed(
    task_id: str,
    code: str,
    message: str,
    worker_result: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Record a Harness failure while preserving an explicit cancellation."""

    global _task

    worker_result = worker_result or {}
    with _task_lock:
        if _task is None or _task["task_id"] != task_id:
            return None
        if _task["state"] == "cancelled":
            return dict(_task)
        _task["state"] = "failed"
        _task["stage"] = "harness"
        _task["seq"] = int(_task["seq"]) + 1
        _task["updated_at"] = utc_now()
        _task["error"] = {
            "code": code,
            "message": message,
            "return_code": worker_result.get("return_code"),
            "worker_log": worker_result.get("worker_log"),
            "result_path": worker_result.get("result_path"),
        }
        return dict(_task)


def run_harness_worker(
    task_id: str,
    input_path: str,
    cancel_event: threading.Event,
) -> None:
    """Run the current Harness outside the HTTP request thread."""

    global _harness_cancel_event

    def on_stage(stage: str, details: dict[str, object]) -> None:
        update_harness_stage(task_id, stage, details)

    try:
        try:
            worker_result = run_harness_task(
                source_audio=Path(input_path),
                out_dir=harness_directory(task_id),
                cancel_event=cancel_event,
                on_stage=on_stage,
                config=HarnessRunConfig(),
            )
        except HarnessWorkerCancelled:
            return
        except HarnessWorkerError as exc:
            mark_harness_failed(task_id, "harness_worker_error", str(exc))
            return
        except Exception as exc:
            mark_harness_failed(task_id, "harness_worker_internal_error", repr(exc))
            return

        if worker_result.get("status") != "succeeded":
            mark_harness_failed(
                task_id,
                "harness_failed",
                "Harness returned a failed result",
                worker_result,
            )
            return

        global _task
        with _task_lock:
            if _task is None or _task["task_id"] != task_id:
                return
            if _task["state"] == "cancelled":
                return
            _task["state"] = "completed"
            _task["stage"] = "meeting_ready"
            _task["harness_result_path"] = worker_result.get("result_path")
            _task["artifact_refs"] = worker_result.get("artifact_refs") or {}
            _task["worker_log"] = worker_result.get("worker_log")
            _task["harness_elapsed_seconds"] = worker_result.get("elapsed_seconds")
            _task["harness_stage_details"] = {"status": "succeeded"}
            _task["seq"] = int(_task["seq"]) + 1
            _task["updated_at"] = utc_now()
    finally:
        with _task_lock:
            if _harness_cancel_event is cancel_event:
                _harness_cancel_event = None


def start_harness_worker(task_id: str, input_path: str) -> None:
    """Create the single background Harness worker for the active task."""

    global _harness_cancel_event

    cancel_event = threading.Event()
    with _task_lock:
        if _task is None or _task["task_id"] != task_id:
            return
        _harness_cancel_event = cancel_event

    worker = threading.Thread(
        target=run_harness_worker,
        args=(task_id, input_path, cancel_event),
        daemon=True,
        name=f"harness-{task_id}",
    )
    worker.start()


def stream_audio_to_disk(
    handler: BaseHTTPRequestHandler,
    task_id: str,
    expected_size: int,
    supplied_sha256: str | None,
) -> dict[str, object]:
    """把 HTTP 请求体流式写入临时文件并验证大小和 SHA-256。

    该函数不持有全局任务锁，因此上传大文件时不会阻塞健康检查或取消请求。
    上传结束后由调用方再次检查任务状态，处理上传期间发生的取消。
    """

    directory = task_directory(task_id)
    directory.mkdir(parents=True, exist_ok=True)

    # 仅作为当前技术探针的最小权限保护。它不是生产级加密存储实现。
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass

    partial_path = directory / "input.wav.part"
    final_path = directory / "input.wav"
    digest = hashlib.sha256()
    received = 0

    try:
        with partial_path.open("wb") as output:
            while received < expected_size:
                remaining = expected_size - received
                chunk_size = min(UPLOAD_CHUNK_BYTES, remaining)
                chunk = handler.rfile.read(chunk_size)

                # Content-Length 声明了长度，但连接提前结束，说明上传不完整。
                if not chunk:
                    raise UploadError(
                        "upload_body_incomplete",
                        "request body ended before Content-Length bytes were received",
                    )

                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)

        actual_sha256 = digest.hexdigest()

        if received != expected_size:
            raise UploadError(
                "upload_size_mismatch",
                f"received {received} bytes but expected {expected_size} bytes",
            )

        if supplied_sha256 is not None and actual_sha256 != supplied_sha256.lower():
            raise UploadError(
                "input_sha256_mismatch",
                "uploaded file SHA-256 does not match X-File-SHA256",
            )

        # 只有全部校验通过后，才将 .part 原子改名为正式临时文件名。
        partial_path.replace(final_path)

        return {
            "input_path": str(final_path),
            "input_size": received,
            "input_sha256": actual_sha256,
            "input_verified": True,
        }
    except Exception:
        # 校验失败、磁盘错误或连接中断都不能留下可被误认为完整的文件。
        shutil.rmtree(directory, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# 当前的通信探针任务
# ---------------------------------------------------------------------------


def run_transport_probe(task_id: str) -> None:
    """运行一个可观察的异步通信探针，不执行真实 NPU 推理。"""

    # 这些延时用于让 PC 端有机会分别查询 created、running 和 completed。
    # 它们不是进度百分比，也不能在正式会议页面中显示为真实处理进度。
    time.sleep(1.0)
    if not advance_task(task_id, "running", "transport_probe"):
        return

    time.sleep(2.0)
    advance_task(task_id, "completed", "transport_probe")


# ---------------------------------------------------------------------------
# HTTP 请求处理器
# ---------------------------------------------------------------------------


class AgentRequestHandler(BaseHTTPRequestHandler):
    """处理开发板 Agent API 的控制面和最小数据面 HTTP 请求。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, format_string: str, *args: object) -> None:
        """保留标准 HTTP 访问日志，并增加 UTC 时间。"""

        print(
            "[%s] %s %s"
            % (
                utc_now(),
                self.address_string(),
                format_string % args,
            ),
            flush=True,
        )

    def do_GET(self) -> None:
        """处理健康检查和任务状态查询。"""

        path = urlparse(self.path).path

        # ------------------------------------------------------------------
        # GET /v1/health
        # ------------------------------------------------------------------
        # PC Gateway 启动或提交任务前先调用该接口，确认板端 Agent 可用。
        if path == "/v1/health":
            current = task_snapshot()
            busy = current is not None and current["state"] not in TERMINAL_STATES

            send_json(
                self,
                200,
                {
                    "status": "ready",
                    "board_id": socket.gethostname(),
                    "protocol_version": PROTOCOL_VERSION,
                    "agent_version": AGENT_VERSION,
                    "model_profile": MODEL_PROFILE,
                    "busy": busy,
                    "active_task_id": (
                        current["task_id"] if busy and current is not None else None
                    ),
                    "local_only": True,
                    "timestamp": utc_now(),
                },
            )
            return

        # ------------------------------------------------------------------
        # GET /v1/tasks/{task_id}/result
        # ------------------------------------------------------------------
        result_match = re.fullmatch(r"/v1/tasks/([^/]+)/result", path)
        if result_match:
            task_id = result_match.group(1)
            current = task_snapshot()
            if current is None or current["task_id"] != task_id:
                send_error_json(self, 404, "task_not_found", "task was not found")
                return
            if current["task_kind"] != HARNESS_TASK_KIND:
                send_error_json(
                    self,
                    409,
                    "result_not_supported",
                    "task does not produce a Harness result",
                )
                return

            result_path = harness_directory(task_id) / "meeting_result.json"
            if not result_path.is_file():
                send_error_json(
                    self,
                    409,
                    "result_not_ready",
                    "Harness meeting_result.json is not ready",
                )
                return
            if result_path.stat().st_size > MAX_RESULT_BYTES:
                send_error_json(
                    self,
                    502,
                    "result_too_large",
                    "Harness result exceeds the Agent API response limit",
                )
                return
            try:
                result_payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                send_error_json(self, 500, "invalid_harness_result", str(exc))
                return
            if not isinstance(result_payload, dict):
                send_error_json(self, 500, "invalid_harness_result", "Harness result must be a JSON object")
                return

            send_json(
                self,
                200,
                {
                    "task_id": task_id,
                    "meeting_id": current["meeting_id"],
                    "result": result_payload,
                    "artifact_refs": current.get("artifact_refs") or {},
                },
            )
            return

        # ------------------------------------------------------------------
        # GET /v1/tasks/{task_id}
        # ------------------------------------------------------------------
        task_match = re.fullmatch(r"/v1/tasks/([^/]+)", path)
        if task_match:
            task_id = task_match.group(1)
            current = task_snapshot()

            if current is None or current["task_id"] != task_id:
                send_error_json(self, 404, "task_not_found", "task was not found")
                return

            send_json(self, 200, current)
            return

        send_error_json(self, 404, "not_found", "endpoint was not found")

    def do_POST(self) -> None:
        """处理任务创建和取消请求。"""

        global _task, _harness_cancel_event

        path = urlparse(self.path).path

        try:
            payload = read_json_body(self)
        except (ValueError, json.JSONDecodeError) as exc:
            send_error_json(self, 400, "invalid_json", str(exc))
            return

        # ------------------------------------------------------------------
        # POST /v1/tasks
        # ------------------------------------------------------------------
        if path == "/v1/tasks":
            task_kind = str(payload.get("task_kind", "transport_probe"))

            # 保留两个通信探针，并增加一个使用当前 Harness 的真实处理测试任务。
            if task_kind not in {"transport_probe", "audio_upload_probe", HARNESS_TASK_KIND}:
                send_error_json(
                    self,
                    400,
                    "unsupported_task_kind",
                    "supported task kinds are transport_probe, audio_upload_probe and "
                    + HARNESS_TASK_KIND,
                )
                return

            meeting_id = payload.get("meeting_id")
            if meeting_id is not None and not isinstance(meeting_id, str):
                send_error_json(
                    self,
                    400,
                    "invalid_meeting_id",
                    "meeting_id must be a string",
                )
                return

            with _task_lock:
                # 当前 MVP 只支持一个活动任务，不做排队和并发。
                if _task is not None and _task["state"] not in TERMINAL_STATES:
                    send_error_json(
                        self,
                        409,
                        "task_already_active",
                        "only one active task is supported",
                    )
                    return

                task_id = "task-" + uuid.uuid4().hex[:12]
                now = utc_now()
                _task = {
                    "task_id": task_id,
                    "meeting_id": meeting_id,
                    "task_kind": task_kind,
                    "state": "created",
                    "stage": (
                        "control_plane"
                        if task_kind == "transport_probe"
                        else "awaiting_audio"
                    ),
                    "seq": 1,
                    "created_at": now,
                    "updated_at": now,
                    "error": None,
                    "input_path": None,
                    "input_size": None,
                    "input_sha256": None,
                    "input_verified": False,
                    "harness_model_profile": (
                        HARNESS_MODEL_PROFILE if task_kind == HARNESS_TASK_KIND else None
                    ),
                    "harness_out_dir": (
                        str(harness_directory(task_id)) if task_kind == HARNESS_TASK_KIND else None
                    ),
                    "harness_result_path": None,
                    "artifact_refs": {},
                    "worker_log": None,
                    "harness_elapsed_seconds": None,
                    "harness_stage_details": None,
                }

            # transport_probe 自动推进；audio_upload_probe 必须等待 PUT audio。
            if task_kind == "transport_probe":
                worker = threading.Thread(
                    target=run_transport_probe,
                    args=(task_id,),
                    daemon=True,
                    name=f"transport-probe-{task_id}",
                )
                worker.start()

            # HTTP 请求立即返回 task_id，后台或后续上传请求继续推进状态。
            send_json(self, 202, task_snapshot() or {})
            return

        # ------------------------------------------------------------------
        # POST /v1/tasks/{task_id}/cancel
        # ------------------------------------------------------------------
        cancel_match = re.fullmatch(r"/v1/tasks/([^/]+)/cancel", path)
        if cancel_match:
            task_id = cancel_match.group(1)
            should_cleanup = False
            should_cancel_harness = False
            harness_cancel_event: threading.Event | None = None

            with _task_lock:
                if _task is None or _task["task_id"] != task_id:
                    send_error_json(self, 404, "task_not_found", "task was not found")
                    return

                # 对已完成、已取消或已失败的任务重复取消时，直接返回当前状态。
                if _task["state"] not in TERMINAL_STATES:
                    _task["state"] = "cancelled"
                    _task["stage"] = (
                        "cancelled"
                        if _task["task_kind"] == HARNESS_TASK_KIND
                        else "control_plane"
                    )
                    _task["seq"] = int(_task["seq"]) + 1
                    _task["updated_at"] = utc_now()
                    should_cleanup = _task["task_kind"] == "audio_upload_probe"
                    should_cancel_harness = _task["task_kind"] == HARNESS_TASK_KIND
                    harness_cancel_event = _harness_cancel_event

                result = dict(_task)

            # 不在状态锁内删除文件，避免文件系统操作阻塞其他控制请求。
            if should_cleanup:
                remove_task_files(task_id)
            if should_cancel_harness and harness_cancel_event is not None:
                harness_cancel_event.set()

            send_json(self, 200, result)
            return

        send_error_json(self, 404, "not_found", "endpoint was not found")

    def do_PUT(self) -> None:
        """处理 PUT /v1/tasks/{task_id}/audio 音频上传请求。"""

        path = urlparse(self.path).path
        audio_match = re.fullmatch(r"/v1/tasks/([^/]+)/audio", path)
        if audio_match is None:
            send_error_json(self, 404, "not_found", "endpoint was not found")
            return

        task_id = audio_match.group(1)

        # 当前探针要求 Content-Length，后续如需支持 chunked 上传再单独设计。
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            send_error_json(
                self,
                411,
                "content_length_required",
                "Content-Length is required for the upload probe",
            )
            return

        try:
            expected_size = int(raw_length)
        except ValueError:
            send_error_json(
                self,
                400,
                "invalid_content_length",
                "Content-Length must be an integer",
            )
            return

        if expected_size <= 0:
            send_error_json(
                self,
                400,
                "invalid_content_length",
                "Content-Length must be positive",
            )
            return

        if expected_size > MAX_UPLOAD_BYTES:
            send_error_json(
                self,
                413,
                "upload_too_large",
                f"upload exceeds {MAX_UPLOAD_BYTES} bytes",
            )
            return

        # MIME 参数可能包含 charset，比较前只保留主类型。
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0]
        content_type = content_type.strip().lower()
        if content_type not in AUDIO_CONTENT_TYPES:
            send_error_json(
                self,
                415,
                "unsupported_content_type",
                "supported content types are audio/wav, audio/x-wav and application/octet-stream",
            )
            return

        supplied_sha256 = self.headers.get("X-File-SHA256")
        if supplied_sha256 is not None:
            supplied_sha256 = supplied_sha256.strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", supplied_sha256) is None:
                send_error_json(
                    self,
                    400,
                    "invalid_sha256",
                    "X-File-SHA256 must be a 64-character hexadecimal digest",
                )
                return

        # 上传探针和 Harness 任务都接收原始 WAV；控制探针仍然拒绝音频。
        with _task_lock:
            if _task is None or _task["task_id"] != task_id:
                send_error_json(self, 404, "task_not_found", "task was not found")
                return

            if _task["task_kind"] not in {"audio_upload_probe", HARNESS_TASK_KIND}:
                send_error_json(
                    self,
                    409,
                    "task_kind_not_uploadable",
                    "task is not an audio_upload_probe or harness_meeting_v0",
                )
                return

            if _task["state"] != "created":
                send_error_json(
                    self,
                    409,
                    "task_not_uploadable",
                    "task is not waiting for audio",
                )
                return

            _task["state"] = "uploading"
            _task["stage"] = "audio_upload"
            _task["seq"] = int(_task["seq"]) + 1
            _task["updated_at"] = utc_now()

        try:
            verified = stream_audio_to_disk(
                self,
                task_id,
                expected_size,
                supplied_sha256,
            )
        except UploadError as exc:
            failure = mark_task_failed(task_id, exc.code, exc.message)
            send_error_json(self, exc.status, exc.code, exc.message)
            if failure is not None:
                print(
                    "[%s] audio upload failed task=%s code=%s"
                    % (utc_now(), task_id, exc.code),
                    flush=True,
                )
            return
        except (ConnectionError, BrokenPipeError, OSError) as exc:
            failure = mark_task_failed(task_id, "upload_io_error", str(exc))
            # 客户端连接可能已经断开，响应本身也可能无法发送。
            try:
                send_error_json(self, 500, "upload_io_error", str(exc))
            except (BrokenPipeError, ConnectionError, OSError):
                pass
            if failure is not None:
                print(
                    "[%s] audio upload I/O failure task=%s error=%r"
                    % (utc_now(), task_id, exc),
                    flush=True,
                )
            return
        except Exception as exc:
            failure = mark_task_failed(task_id, "upload_internal_error", str(exc))
            try:
                send_error_json(self, 500, "upload_internal_error", str(exc))
            except (BrokenPipeError, ConnectionError, OSError):
                pass
            if failure is not None:
                print(
                    "[%s] audio upload internal failure task=%s error=%r"
                    % (utc_now(), task_id, exc),
                    flush=True,
                )
            return

        # 上传期间可能收到取消请求。取消优先，不能把已取消任务改回 processing/completed。
        start_harness = False
        harness_input_path: str | None = None
        response_status = 200
        with _task_lock:
            if _task is None or _task["task_id"] != task_id:
                remove_task_files(task_id)
                send_error_json(self, 404, "task_not_found", "task was not found")
                return

            if _task["state"] == "cancelled":
                remove_task_files(task_id)
                send_error_json(self, 409, "task_cancelled", "task was cancelled during upload")
                return

            if _task["state"] != "uploading":
                remove_task_files(task_id)
                send_error_json(self, 409, "task_state_conflict", "task state changed during upload")
                return

            _task.update(verified)
            if _task["task_kind"] == HARNESS_TASK_KIND:
                _task["state"] = "processing"
                _task["stage"] = "segmentation"
                _task["harness_stage_details"] = {"status": "starting"}
                harness_input_path = str(_task["input_path"])
                start_harness = True
                response_status = 202
            else:
                _task["state"] = "completed"
                _task["stage"] = "input_verified"
            _task["seq"] = int(_task["seq"]) + 1
            _task["updated_at"] = utc_now()
            result = dict(_task)

        if start_harness and harness_input_path is not None:
            try:
                start_harness_worker(task_id, harness_input_path)
            except Exception as exc:
                mark_harness_failed(task_id, "harness_start_failed", repr(exc))
                result = task_snapshot() or result

        send_json(self, response_status, result)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """允许开发阶段快速重启服务，并让每个请求使用独立线程。"""

    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    """启动 Agent API，直到进程收到 Ctrl+C。"""

    server = ReusableThreadingHTTPServer(
        (DEFAULT_HOST, DEFAULT_PORT),
        AgentRequestHandler,
    )
    print(
        "board-agent-api listening on %s:%s protocol=%s"
        % (DEFAULT_HOST, DEFAULT_PORT, PROTOCOL_VERSION),
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("board-agent-api stopping", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
