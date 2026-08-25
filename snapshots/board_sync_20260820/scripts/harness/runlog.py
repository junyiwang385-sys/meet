"""单次 Harness 运行的结构化 sidecar 日志。"""

# 这个模块只负责写 sidecar 可观测性文件。
# 它不改变核心 meeting_result.json 的业务 schema。
# 目标是让每次 run 都可追踪、可关联、可回放，而不是把日志变成生产控制流的一部分。

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any

from . import HARNESS_VERSION, RESULT_SCHEMA_VERSION
from .artifacts import HarnessPaths, atomic_write_json, relative_artifact, sha256_file

# 这些 sidecar schema 版本与主 Harness result schema 独立演进，
# 因此日志可以迭代，而不需要每次都推动业务结果 schema 升级。
RUN_MANIFEST_SCHEMA_VERSION = "run-manifest.v1"
RUN_EVENT_SCHEMA_VERSION = "run-event.v1"
RUN_METRICS_SCHEMA_VERSION = "run-metrics.v1"
ERROR_REPORT_SCHEMA_VERSION = "error-report.v1"

# 错误类别会归一化成一套共享词汇，方便 board 侧轮询、
# 后续诊断和测试都围绕同一种失败形状来理解问题。
STAGE_ERROR_CATEGORIES = {
    "preflight": "environment",
    "segmentation": "segmentation",
    "batch_asr": "asr",
    "transcript_prepare": "transcript",
    "llm_summary": "llm",
    "compat_export": "export",
    "pipeline": "unknown",
}

CODE_ERROR_CATEGORIES = {
    "missing_script": "environment",
    "invalid_previous_config": "environment",
    "process_failed": "resource",
    "invalid_artifacts": "validation",
    "validation_failed": "validation",
    "request_failed": "llm",
    "export_failed": "export",
    "internal_error": "unknown",
}

RETRYABLE_CATEGORIES = {"environment", "resource", "segmentation", "asr", "llm", "export", "unknown"}
# 某些业务校验错误虽然属于 validation 类别，但仍然可以通过受控重试或拆批恢复。
# 这些 cause 用来补足单纯按 category 判断 retryable 的不足。
RETRYABLE_ERROR_CAUSES = {
    "finish_reason_length",
    "context_truncated",
    "invalid_json",
    "missing_speaker_summaries",
}

# 控制内联 payload 的大小，确保 JSONL 事件仍然可读，
# 也避免在每条记录里重复大段 prompt、转写内容或堆栈。
MAX_INLINE_TEXT = 6000


def now_iso() -> str:
    """Return a UTC timestamp with one stable, cross-platform representation."""

    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _safe_text(value: Any, limit: int = MAX_INLINE_TEXT) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[-limit:]


def error_category(stage: str | None, code: str | None) -> str:
    if code in CODE_ERROR_CATEGORIES:
        return CODE_ERROR_CATEGORIES[code]
    if stage in STAGE_ERROR_CATEGORIES:
        return STAGE_ERROR_CATEGORIES[stage]
    return "unknown"


def _infer_error_cause(code: str, message: str) -> str | None:
    """Infer a small stable cause code without depending on free-form text upstream."""

    lowered = message.casefold()
    if "finish_reason" in lowered and "length" in lowered:
        return "finish_reason_length"
    if "context_truncated" in lowered or "input was truncated" in lowered:
        return "context_truncated"
    if code == "invalid_json" or "not valid json" in lowered:
        return "invalid_json"
    if code == "missing_speaker_summaries" or "missing speaker summaries" in lowered:
        return "missing_speaker_summaries"
    return None


def normalize_error(error: Any) -> dict[str, Any]:
    """Normalize errors while preserving bounded request and retry context.

    ``retryable`` remains as a backwards-compatible alias for the product-level
    retry decision.  New consumers should use ``technical_retryable`` and
    ``product_retryable`` separately.
    """

    if isinstance(error, dict):
        stage = str(error.get("stage") or "pipeline")
        code = str(error.get("code") or "unknown")
        message = str(error.get("message") or error.get("error") or "")
        category = error_category(stage, code)
        cause = str(error.get("cause") or _infer_error_cause(code, message) or "") or None
        technical_retryable = error.get("technical_retryable")
        if not isinstance(technical_retryable, bool):
            technical_retryable = category in RETRYABLE_CATEGORIES or cause in RETRYABLE_ERROR_CAUSES
        product_retryable = error.get("product_retryable")
        if not isinstance(product_retryable, bool):
            product_retryable = technical_retryable
        result = {
            "stage": stage,
            "code": code,
            "category": category,
            "message": _safe_text(message),
            "technical_retryable": technical_retryable,
            "product_retryable": product_retryable,
            # Keep the old field during migration so existing Board/Gateway code
            # can consume the new report without a flag day.
            "retryable": product_retryable,
        }
        passthrough_keys = (
            "artifact",
            "return_code",
            "request_id",
            "request_kind",
            "attempt",
            "split_depth",
            "finish_reason",
            "context_truncated",
            "usage",
            "request_elapsed_seconds",
            "retry_scope",
        )
        for key in passthrough_keys:
            if key in error:
                result[key] = _jsonable(error[key])
        if cause is not None:
            result["cause"] = cause
        return result

    message = _safe_text(error)
    return {
        "stage": "pipeline",
        "code": "internal_error",
        "category": "unknown",
        "message": message,
        "technical_retryable": True,
        "product_retryable": True,
        "retryable": True,
    }


def _last_event_seq(path: pathlib.Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        seq = value.get("seq") if isinstance(value, dict) else None
        if isinstance(seq, int):
            return seq
    return 0


@dataclass(frozen=True)
class RunIdentity:
    trace_id: str
    meeting_id: str
    task_id: str
    run_id: str

    @classmethod
    def from_args_result(cls, args: Any, result: dict[str, Any]) -> "RunIdentity":
        meeting = result.get("meeting") if isinstance(result.get("meeting"), dict) else {}
        run_id = str(getattr(args, "run_id", None) or result.get("run_id") or "run_local")
        meeting_id = str(getattr(args, "meeting_id", None) or meeting.get("meeting_id") or run_id)
        task_id = str(getattr(args, "task_id", None) or "local")
        trace_id = str(getattr(args, "trace_id", None) or f"tr_{run_id}")
        return cls(trace_id=trace_id, meeting_id=meeting_id, task_id=task_id, run_id=run_id)

    def as_dict(self) -> dict[str, str]:
        return {
            "trace_id": self.trace_id,
            "meeting_id": self.meeting_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
        }


class RunLogContext:
    """作用域限定在单个 Harness 输出目录的追加式结构化日志器。"""

    def __init__(self, paths: HarnessPaths, identity: RunIdentity) -> None:
        self.paths = paths
        self.identity = identity
        # 续跑时要接着上一次的事件序号往后写，避免同一 run 的 JSONL 序号回退或重复。
        self._seq = _last_event_seq(paths.run_events)

    def emit(
        self,
        event: str,
        *,
        stage: str = "pipeline",
        level: str = "info",
        message: str | None = None,
        duration_ms: int | None = None,
        metrics: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | list[Any] | None = None,
        error: Any = None,
        details: dict[str, Any] | None = None,
        source: str | None = None,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 每条事件都携带 identity 和递增序号，方便后续把多份 sidecar 还原成同一条时间线。
        self._seq += 1
        record: dict[str, Any] = {
            "schema_version": RUN_EVENT_SCHEMA_VERSION,
            "seq": self._seq,
            "ts": now_iso(),
            "level": level,
            **self.identity.as_dict(),
            "stage": stage,
            "event": event,
        }
        if source is not None:
            record["source"] = source
        if message is not None:
            record["message"] = _safe_text(message)
        if duration_ms is not None:
            record["duration_ms"] = duration_ms
        if metrics is not None:
            record["metrics"] = _jsonable(metrics)
        if artifacts is not None:
            record["artifacts"] = _jsonable(artifacts)
        if error is not None:
            record["error"] = normalize_error(error)
        if request is not None:
            record["request"] = _jsonable(request)
        if details is not None:
            record["details"] = _jsonable(details)

        # JSONL 采用追加写；每次写完都 flush + fsync，尽量把崩溃窗口压到最小。
        self.paths.run_events.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.run_events.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def stage_started(self, stage: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.emit("stage_started", stage=stage, message=f"{stage} 开始执行", details=details)

    def stage_succeeded(self, stage: str, stage_result: dict[str, Any] | None = None) -> dict[str, Any]:
        duration_ms = None
        metrics: dict[str, Any] = {}
        if isinstance(stage_result, dict):
            elapsed = stage_result.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)):
                duration_ms = int(round(float(elapsed) * 1000))
            for key in ("return_code", "request_count", "validated_request_count", "reused_request_count"):
                if key in stage_result:
                    metrics[key] = stage_result[key]
        return self.emit(
            "stage_succeeded",
            stage=stage,
            message=f"{stage} 执行成功",
            duration_ms=duration_ms,
            metrics=metrics or None,
        )

    def stage_failed(self, stage: str, error: Any, stage_result: dict[str, Any] | None = None) -> dict[str, Any]:
        duration_ms = None
        if isinstance(stage_result, dict):
            elapsed = stage_result.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)):
                duration_ms = int(round(float(elapsed) * 1000))
        return self.emit(
            "stage_failed",
            stage=stage,
            level="error",
            message=f"{stage} 执行失败",
            duration_ms=duration_ms,
            error=error,
        )

    def stage_skipped(self, stage: str, reason: str, status: str = "skipped") -> dict[str, Any]:
        # 保留机器可读的 status，同时把 message 翻成中文，方便人眼快速扫日志。
        status_label = {
            "reused": "已重用",
            "skipped": "已跳过",
        }.get(status, f"状态为{status}")
        return self.emit(
            "stage_skipped",
            stage=stage,
            message=f"{stage} {status_label}",
            details={"status": status, "reason": reason},
        )

    def artifact_written(self, name: str, path: pathlib.Path, stage: str = "pipeline") -> dict[str, Any]:
        return self.emit(
            "artifact_written",
            stage=stage,
            message=f"已写入产物：{name}",
            artifacts={name: relative_artifact(path, self.paths.root)},
        )

    def write_manifest(
        self,
        *,
        args: Any,
        source_audio: pathlib.Path,
        result: dict[str, Any],
        config_identity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # manifest 是单次 run 的静态快照：输入、身份、输出目录、配置和 sidecar 路径都要能对上。
        source_audio = pathlib.Path(source_audio)
        source = result.get("meeting") if isinstance(result.get("meeting"), dict) else {}
        args_dict = {key: _jsonable(value) for key, value in vars(args).items()}
        manifest = {
            "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
            "generated_at": now_iso(),
            "identity": self.identity.as_dict(),
            "harness_version": HARNESS_VERSION,
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "source_audio": {
                "path": str(source_audio),
                "sha256": source.get("source_audio_sha256") or sha256_file(source_audio),
                "size_bytes": source.get("source_audio_size_bytes") or source_audio.stat().st_size,
            },
            "output_dir": str(self.paths.root),
            "config": args_dict,
            "config_identity": _jsonable(config_identity) if config_identity is not None else None,
            "sidecars": {
                "run_events": str(self.paths.run_events.relative_to(self.paths.root)),
                "run_metrics": str(self.paths.run_metrics.relative_to(self.paths.root)),
                "error_report": str(self.paths.error_report.relative_to(self.paths.root)),
                "stage_status": str(self.paths.stage_status.relative_to(self.paths.root)),
            },
        }
        atomic_write_json(self.paths.run_manifest, manifest)
        return manifest

    def write_error_report(
        self,
        error: Any,
        *,
        result: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 错误报告要把“发生了什么”和“去哪里看”放在一起，方便后续人工和 Agent 二次诊断。
        normalized = normalize_error(error)
        stage = normalized.get("stage")
        stages = state.get("stages", {}) if isinstance(state, dict) else {}
        stage_details = stages.get(stage) if isinstance(stages, dict) else None
        log_tail = None
        if isinstance(stage_details, dict) and isinstance(stage_details.get("log_tail"), str):
            log_tail = _safe_text(stage_details["log_tail"])

        report = {
            "schema_version": ERROR_REPORT_SCHEMA_VERSION,
            "generated_at": now_iso(),
            "identity": self.identity.as_dict(),
            "status": "failed",
            "error": normalized,
            "stage_details": _jsonable(stage_details) if isinstance(stage_details, dict) else None,
            "log_tail": log_tail,
            "diagnosis": {
                "agent_enabled": False,
                "inputs": {
                    "run_manifest": str(self.paths.run_manifest.relative_to(self.paths.root)),
                    "run_events": str(self.paths.run_events.relative_to(self.paths.root)),
                    "stage_status": str(self.paths.stage_status.relative_to(self.paths.root)),
                    "error_report": str(self.paths.error_report.relative_to(self.paths.root)),
                },
            },
            "result_status": result.get("status") if isinstance(result, dict) else None,
        }
        atomic_write_json(self.paths.error_report, report)
        return report

    def write_metrics(
        self,
        *,
        result: dict[str, Any],
        state: dict[str, Any],
        memory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 指标文件负责做最终汇总，不追求逐秒细节，重点是阶段计数、耗时和资源概览。
        runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
        stages = runtime.get("stages") if isinstance(runtime.get("stages"), dict) else state.get("stages", {})
        stage_counts: dict[str, int] = {}
        stage_elapsed_seconds: dict[str, float] = {}
        if isinstance(stages, dict):
            for name, item in stages.items():
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "unknown")
                stage_counts[status] = stage_counts.get(status, 0) + 1
                elapsed = item.get("elapsed_seconds")
                if isinstance(elapsed, (int, float)):
                    stage_elapsed_seconds[str(name)] = round(float(elapsed), 3)

        metrics = {
            "schema_version": RUN_METRICS_SCHEMA_VERSION,
            "generated_at": now_iso(),
            "identity": self.identity.as_dict(),
            "status": result.get("status"),
            "total_elapsed_seconds": runtime.get("total_elapsed_seconds"),
            "stage_counts": stage_counts,
            "stage_elapsed_seconds": stage_elapsed_seconds,
            "llm": _jsonable(runtime.get("llm") or {}),
            "memory": _jsonable(memory or runtime.get("memory") or {}),
            "error_count": len(result.get("errors") or []) if isinstance(result.get("errors"), list) else 0,
            "artifact_count": len(result.get("artifacts") or {}) if isinstance(result.get("artifacts"), dict) else 0,
        }
        atomic_write_json(self.paths.run_metrics, metrics)
        return metrics
