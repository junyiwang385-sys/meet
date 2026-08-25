"""rkllm3-server lifecycle and evidence-linked meeting summarization requests."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .artifacts import atomic_write_json, atomic_write_text


MODEL_SUFFIXES = {
    "model": ".rknn",
    "weight": ".weight",
    "vocab": ".tokenizer.gguf",
    "embed": ".embed.bin",
}
TRUNCATION_MARKERS = ("input truncated", "truncated: n_ctx", "exceeds the context")
PROMPT_VERSION = "meeting-summary.v3"


def _emit_run_log(
    run_log: Any | None,
    event: str,
    *,
    stage: str,
    level: str = "info",
    message: str | None = None,
    request: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Best-effort bridge from transport events to the run-level event stream.

    Request sidecar files remain the detailed evidence.  The run log receives
    only bounded metadata so a logging I/O problem cannot turn a valid LLM
    response into a business failure.
    """

    if run_log is None:
        return
    try:
        run_log.emit(
            event,
            stage=stage,
            level=level,
            message=message,
            request=request,
            error=error,
            details=details,
            source="llm",
        )
    except (OSError, TypeError, ValueError):
        # Observability is deliberately non-blocking for the inference path.
        return


SYSTEM_PROMPT = """你是会议事实整理器，只能依据当前请求中提供的会议内容生成结果。
允许先在 <think>...</think> 中进行推理；思考结束后只能输出一个合法 JSON 对象，不要输出 Markdown、解释或代码围栏。
不得虚构输入中没有的事实、数字、决定、风险、负责人或截止时间。
不同请求可能提供完整 Timeline，也可能只提供章节摘要、待办候选或证据 JSON。Timeline 文本使用紧凑格式 [r38][14m48s-15m12s][sp3] 内容；r38 是 segment 的唯一引用 ID，时间全部使用分钟 m 和秒 s，sp3 是匿名 speaker 标识。即使当前请求没有 Timeline 行，字段中的 segment_id、refs、speaker_id 和 owner 仍使用同一套紧凑 r/sp ID；所有 ID 必须原样使用当前输入中出现的值，不要修改、补造或转换。
普通讨论、建议和观点不能自动升级为决定或待办。
没有明确依据的标量使用 null，没有明确依据的集合使用 []，不要用“暂无”“未明确”“N/A”等占位文字代替空值。"""

SUMMARY_SHAPE = {
    "title": "会议标题或 null",
    "overview": {"text": "内容概述", "refs": ["r1"]},
    "chapters": [
        {
            "title": "章节标题",
            "overview": "章节概述",
            "start_ref": "r1",
            "end_ref": "r10",
            "refs": ["r1", "r10"],
        }
    ],
    "speakers": [
        {"speaker_id": "sp1", "overview": "主要贡献", "refs": ["r1"]}
    ],
    "key_points": [],
    "decisions": [{"text": "明确达成的决定", "refs": ["r1"]}],
    "action_items": [
        {
            "task": "明确提出的后续事项",
            "owner": "speaker_A 或 null",
            "deadline": "原文明确出现的截止时间或 null",
            "refs": ["r1"],
        }
    ],
    "open_questions": [{"text": "明确尚未解决的问题", "refs": ["r1"]}],
    "risks": [{"text": "明确提及的风险或依赖", "refs": ["r1"]}],
    "keywords": [{"keyword": "关键词", "refs": ["r1"]}],
}


@dataclass(frozen=True)
class LlmConfig:
    board_scripts_dir: pathlib.Path
    model_dir: pathlib.Path
    server: pathlib.Path
    host: str
    port: int
    ctx: int
    predict: int
    max_tokens: int
    temperature: float
    server_temp: float
    server_top_k: int
    server_top_p: float
    server_repeat_penalty: float
    ready_timeout: int
    request_timeout: int


class LlmRunError(RuntimeError):
    pass


def load_board_helpers(board_scripts_dir: pathlib.Path):
    helper_path = board_scripts_dir / "board_meeting_chain_profile.py"
    if not helper_path.is_file():
        raise FileNotFoundError(f"missing board helper: {helper_path}")
    spec = importlib.util.spec_from_file_location("meeting_harness_board_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load board helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_model_files(model_dir: pathlib.Path) -> dict[str, str]:
    files = {}
    for name, suffix in MODEL_SUFFIXES.items():
        matches = sorted(model_dir.glob(f"*{suffix}"))
        if len(matches) != 1:
            raise LlmRunError(f"expected one *{suffix} in {model_dir}, found: {matches}")
        if not matches[0].is_file():
            raise LlmRunError(f"model artifact is not a file: {matches[0]}")
        files[name] = str(matches[0])
    return files


def ensure_port_available(host: str, port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        if probe.connect_ex((host, port)) == 0:
            raise LlmRunError(f"LLM server port is already in use: {host}:{port}")
    finally:
        probe.close()


def build_server_cmd(config: LlmConfig, files: dict[str, str]) -> list[str]:
    return [
        str(config.server),
        "-m", files["model"],
        "--weight", files["weight"],
        "--vocab", files["vocab"],
        "--embed", files["embed"],
        "-c", str(config.ctx),
        "-n", str(config.predict),
        "--temp", str(config.server_temp),
        "--top-k", str(config.server_top_k),
        "--top-p", str(config.server_top_p),
        "--repeat-penalty", str(config.server_repeat_penalty),
        "--host", config.host,
        "--port", str(config.port),
    ]


def _shape_text() -> str:
    return json.dumps(SUMMARY_SHAPE, ensure_ascii=False, indent=2)


def build_full_messages(timeline: str, speaker_ids: list[str]) -> list[dict[str, str]]:
    user_prompt = (
        "这是完整会议时间线，不存在后续窗口。\n"
        f"允许的 speaker_id：{json.dumps(speaker_ids, ensure_ascii=False)}\n"
        "请严格按下列 JSON 结构输出。数组无事实时返回 []，overview 无事实时返回 null。\n"
        f"{_shape_text()}\n\n"
        "会议时间线：\n"
        f"{timeline}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_chunk_messages(
    timeline: str,
    speaker_ids: list[str],
    *,
    chunk_id: str,
    coverage_start_ms: int,
    coverage_end_ms: int,
) -> list[dict[str, str]]:
    user_prompt = (
        f"这是整场会议的一个连续分段（{chunk_id}），不是完整会议。\n"
        f"本段覆盖时间为 {coverage_start_ms}ms 至 {coverage_end_ms}ms。\n"
        "只能总结本段提供的事实，不得声称覆盖整场会议。后续程序会将多个分段结果合并。\n"
        f"允许的 speaker_id：{json.dumps(speaker_ids, ensure_ascii=False)}\n"
        "请严格按下列 JSON 结构输出。refs 只能引用本段时间线中出现的 segment_id。\n"
        f"{_shape_text()}\n\n"
        "会议分段时间线：\n"
        f"{timeline}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_merge_messages(
    summaries: list[dict[str, Any]],
    *,
    merge_id: str,
) -> list[dict[str, str]]:
    payload = json.dumps(summaries, ensure_ascii=False, indent=2)
    user_prompt = (
        f"下面是按会议时间顺序排列、已经通过 refs 校验的局部会议摘要（{merge_id}）。\n"
        "请将它们去重并合并为一个更完整的会议摘要。只能使用输入中已有的事实和 refs；"
        "不得创造新的 segment_id、负责人、截止时间、决定或风险。\n"
        "相同事实跨分段重复出现时合并为一项，并保留足够的原始 refs。\n"
        "请严格按下列 JSON 结构输出。\n"
        f"{_shape_text()}\n\n"
        "已校验的局部摘要：\n"
        f"{payload}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# Backward-compatible name used by older callers.
def build_messages(timeline: str, speaker_ids: list[str]) -> list[dict[str, str]]:
    return build_full_messages(timeline, speaker_ids)


def log_reports_truncation(log_text: str) -> bool:
    lowered = log_text.lower()
    return any(marker in lowered for marker in TRUNCATION_MARKERS)


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if not lines:
        return cleaned
    lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def split_assistant_output(message: dict[str, Any]) -> dict[str, str]:
    raw_content = str(message.get("content") or "")
    dedicated_reasoning = message.get("reasoning_content")
    cleaned = raw_content.strip()
    inline_thinking = ""
    final_content = cleaned
    inline_source = "none"
    if cleaned.startswith("<think>"):
        think_end = cleaned.find("</think>")
        if think_end < 0:
            raise LlmRunError("LLM response started with <think> but has no closing </think>")
        inline_thinking = cleaned[len("<think>"):think_end].strip()
        final_content = cleaned[think_end + len("</think>"):].strip()
        inline_source = "inline_think"
    elif "</think>" in cleaned:
        think_end = cleaned.find("</think>")
        inline_thinking = cleaned[:think_end].strip()
        final_content = cleaned[think_end + len("</think>"):].strip()
        inline_source = "inline_think_closing_only"

    if dedicated_reasoning is not None:
        dedicated = str(dedicated_reasoning).strip()
        thinking = "\n\n".join(part for part in (dedicated, inline_thinking) if part)
        source = "reasoning_content+inline" if inline_thinking else "reasoning_content"
    else:
        thinking = inline_thinking
        source = inline_source
    final_content = _strip_code_fence(final_content)
    if not final_content:
        raise LlmRunError("LLM response has no final content after thinking")
    return {
        "raw_content": raw_content,
        "thinking": thinking,
        "final_content": final_content,
        "thinking_source": source,
    }


# Backward-compatible helper.
def extract_summary_content(content: str) -> str:
    return split_assistant_output({"content": content})["final_content"]


class RkllmServerSession:
    def __init__(
        self,
        config: LlmConfig,
        out_dir: pathlib.Path,
        sampler: Any | None = None,
    ) -> None:
        self.config = config
        self.out_dir = out_dir
        self.sampler = sampler
        self.helpers = load_board_helpers(config.board_scripts_dir)
        self.files = discover_model_files(config.model_dir)
        self.command = build_server_cmd(config, self.files)
        self.log_path = out_dir / "rkllm_server.log"
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle: Any | None = None
        self.ready_seconds: float | None = None
        self.started_at: float | None = None
        self.request_count = 0
        self.successful_response_count = 0

    def __enter__(self) -> "RkllmServerSession":
        try:
            self.start()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        ensure_port_available(self.config.host, self.config.port)
        atomic_write_json(self.out_dir / "llm_cmd.json", self.command)
        self.log_handle = self.log_path.open("wb")
        self.started_at = time.time()
        if self.sampler is not None:
            self.sampler.set_phase("llm_server_start")
        self.process = subprocess.Popen(
            self.command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
        )
        if self.sampler is not None:
            self.sampler.add_target("rkllm_server", self.process.pid)
        ready_started = time.time()
        while time.time() - ready_started < self.config.ready_timeout:
            return_code = self.process.poll()
            if return_code is not None:
                raise LlmRunError(
                    f"rkllm3-server exited before ready; return_code={return_code}"
                )
            try:
                urllib.request.urlopen(
                    f"http://{self.config.host}:{self.config.port}/health", timeout=1
                ).read()
                self.ready_seconds = round(time.time() - ready_started, 3)
                return
            except Exception:
                time.sleep(1)
        raise LlmRunError("rkllm3-server did not become ready before timeout")

    def request(
        self,
        messages: list[dict[str, str]],
        request_dir: pathlib.Path,
        *,
        max_tokens: int | None = None,
        phase: str = "llm_summary",
        request_id: str = "request",
        request_kind: str = "unknown",
        attempt: int = 1,
        estimated_prompt_tokens: int | None = None,
        run_log: Any | None = None,
    ) -> dict[str, Any]:
        if self.process is None or self.process.poll() is not None:
            raise LlmRunError("rkllm3-server is not running")
        request_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": "default",
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }
        atomic_write_json(request_dir / "messages.json", messages)
        atomic_write_json(request_dir / "request.json", payload)
        log_offset = self.log_path.stat().st_size if self.log_path.is_file() else 0
        if self.sampler is not None:
            self.sampler.set_phase(phase)
        request_started = time.time()
        request_meta: dict[str, Any] = {
            "request_id": request_id,
            "request_kind": request_kind,
            "attempt": attempt,
            "phase": phase,
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "max_tokens": payload["max_tokens"],
        }
        _emit_run_log(
            run_log,
            "request_started",
            stage=phase,
            message="LLM 请求已开始",
            request=request_meta,
        )

        def emit_request_failed(code: str, message: str) -> None:
            _emit_run_log(
                run_log,
                "request_failed",
                stage=phase,
                level="error",
                message="LLM 请求失败",
                request={**request_meta, "request_elapsed_seconds": round(time.time() - request_started, 3)},
                error={
                    "stage": phase,
                    "code": code,
                    "message": message,
                    "request_id": request_id,
                    "request_kind": request_kind,
                    "attempt": attempt,
                    "request_elapsed_seconds": round(time.time() - request_started, 3),
                },
            )

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"http://{self.config.host}:{self.config.port}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self.request_count += 1
        try:
            raw_http = urllib.request.urlopen(
                request, timeout=self.config.request_timeout
            ).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw_http = exc.read().decode("utf-8", "replace")
            atomic_write_text(request_dir / "response_http.txt", raw_http)
            emit_request_failed("http_error", f"LLM HTTP error: {exc.code}")
            raise LlmRunError(f"LLM HTTP error: {exc.code}") from exc
        except http.client.IncompleteRead as exc:
            raw_http = exc.partial.decode("utf-8", "replace")
            atomic_write_text(request_dir / "response_http.txt", raw_http)
            message = f"LLM HTTP response ended early after {len(exc.partial)} bytes"
            emit_request_failed("incomplete_response", message)
            raise LlmRunError(message) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            message = f"LLM HTTP request failed: {exc}"
            emit_request_failed("request_failed", message)
            raise LlmRunError(message) from exc
        request_seconds = round(time.time() - request_started, 3)
        atomic_write_text(request_dir / "response_http.txt", raw_http)
        try:
            response = json.loads(raw_http)
        except json.JSONDecodeError as exc:
            error_message = f"LLM HTTP body is not valid JSON: {exc}"
            emit_request_failed("invalid_json", error_message)
            raise LlmRunError(error_message) from exc
        if not isinstance(response, dict):
            error_message = "LLM HTTP response must be a JSON object"
            emit_request_failed("invalid_response", error_message)
            raise LlmRunError(error_message)
        atomic_write_json(request_dir / "response.json", response)

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            error_message = "LLM response has no first choice"
            emit_request_failed("invalid_response", error_message)
            raise LlmRunError(error_message)
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            error_message = "LLM response choice has no message object"
            emit_request_failed("invalid_response", error_message)
            raise LlmRunError(error_message)
        split = split_assistant_output(message)
        atomic_write_text(request_dir / "raw_content.txt", split["raw_content"])
        # Preserve legacy file names for existing result inspection tools.
        atomic_write_text(request_dir / "response_content.txt", split["raw_content"])
        atomic_write_text(request_dir / "thinking.txt", split["thinking"])
        atomic_write_text(request_dir / "final_json.txt", split["final_content"])
        atomic_write_text(request_dir / "response_summary_content.txt", split["final_content"])
        if self.log_handle is not None:
            self.log_handle.flush()
        request_log = ""
        if self.log_path.is_file():
            with self.log_path.open("rb") as handle:
                handle.seek(log_offset)
                request_log = handle.read().decode("utf-8", "replace")
        context_truncated = log_reports_truncation(request_log)
        self.successful_response_count += 1
        result = {
            "status": "ok",
            "request_id": request_id,
            "content": split["final_content"],
            "thinking": split["thinking"],
            "thinking_source": split["thinking_source"],
            "finish_reason": choice.get("finish_reason"),
            "usage": response.get("usage"),
            "timings": response.get("timings"),
            "request_elapsed_seconds": request_seconds,
            "server_ready_seconds": self.ready_seconds,
            "resolved_model_files": self.files,
            "server_pid": self.process.pid,
            "context_truncated": context_truncated,
        }
        _emit_run_log(
            run_log,
            "response_received",
            stage=phase,
            message="LLM 响应已接收",
            request={
                **request_meta,
                "finish_reason": result["finish_reason"],
                "context_truncated": result["context_truncated"],
                "usage": result["usage"],
                "timings": result["timings"],
                "request_elapsed_seconds": result["request_elapsed_seconds"],
            },
        )
        atomic_write_json(
            request_dir / "status.json",
            {key: value for key, value in result.items() if key not in {"content", "thinking"}},
        )
        return result

    def close(self) -> None:
        if self.sampler is not None:
            self.sampler.set_phase("llm_cleanup")
        return_code = None
        if self.process is not None:
            self.helpers.terminate_process(self.process)
            return_code = self.process.poll()
        if self.log_handle is not None:
            self.log_handle.close()
        elapsed = None
        if self.started_at is not None:
            elapsed = round(time.time() - self.started_at, 3)
        log_text = (
            self.log_path.read_text(encoding="utf-8", errors="replace")
            if self.log_path.is_file()
            else ""
        )
        atomic_write_json(
            self.out_dir / "server_status.json",
            {
                "ready_seconds": self.ready_seconds,
                "elapsed_seconds": elapsed,
                "return_code": return_code,
                "request_count": self.request_count,
                "successful_response_count": self.successful_response_count,
                "context_truncated": log_reports_truncation(log_text),
            },
        )
        self.process = None
        self.log_handle = None


def run_single_request(
    config: LlmConfig,
    timeline: str,
    speaker_ids: list[str],
    out_dir: pathlib.Path,
    sampler: Any | None = None,
) -> dict[str, Any]:
    if config.predict < config.max_tokens:
        raise ValueError("predict must be greater than or equal to max_tokens")
    messages = build_full_messages(timeline, speaker_ids)
    started = time.time()
    with RkllmServerSession(config, out_dir, sampler) as session:
        result = session.request(messages, out_dir, request_id="full")
    result["elapsed_seconds"] = round(time.time() - started, 3)
    return result
