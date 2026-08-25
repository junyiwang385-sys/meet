"""单次 Harness 运行的结构化 sidecar 日志。"""

# 这个模块只负责写 sidecar 可观测性文件。
# 它不改变核心 meeting_result.json 的业务 schema。
# 目标是让每次 run 都可追踪、可关联、可回放，而不是把日志变成生产控制流的一部分。

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
from typing import Any

from ..contracts.results import (
    ERROR_REPORT_SCHEMA_VERSION,
    HARNESS_VERSION,
    RESULT_SCHEMA_VERSION,
    RUN_EVENT_SCHEMA_VERSION,
    RUN_MANIFEST_SCHEMA_VERSION,
    RUN_METRICS_SCHEMA_VERSION,
)
from ..contracts.identity import RunIdentity
from ..storage.artifacts import HarnessPaths, atomic_write_json, relative_artifact, sha256_file
from .error_report import build_error_report
from .metrics import build_metrics


def now_iso() -> str:
    """Return a UTC timestamp with one stable, cross-platform representation."""
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

# 这些 sidecar schema 版本与主 Harness result schema 独立演进，
# 因此日志可以迭代，而不需要每次都推动业务结果 schema 升级。

# 错误类别会归一化成一套共享词汇，方便 board 侧轮询、
# 后续诊断和测试都围绕同一种失败形状来理解问题。
from ..contracts.errors import (
    CODE_ERROR_CATEGORIES,
    MAX_INLINE_TEXT,
    RETRYABLE_CATEGORIES,
    RETRYABLE_ERROR_CAUSES,
    STAGE_ERROR_CATEGORIES,
    _jsonable,
    _safe_text,
    error_category,
    normalize_error,
)

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


class RunLogContext:
    """作用域限定在单个 Harness 输出目录的追加式结构化日志器。"""

    def __init__(self, paths: HarnessPaths, identity: RunIdentity) -> None:
        self.paths = paths
        self.identity = identity
        # 续跑时要接着上一次的事件序号往后写，避免同一 run 的 JSONL 序号回退或重复。
        self._seq = _last_event_seq(paths.run_events)
        self.write_error_count = 0

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
        # 结构化日志是诊断增强层，不能因为磁盘或权限异常阻断业务结果收尾。
        try:
            self.paths.run_events.parent.mkdir(parents=True, exist_ok=True)
            with self.paths.run_events.open("a", encoding="utf-8", newline="") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, UnicodeError):
            self.write_error_count += 1
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
        report = build_error_report(
            error,
            identity=self.identity,
            paths=self.paths,
            result=result,
            state=state,
        )
        atomic_write_json(self.paths.error_report, report)
        return report

    def write_metrics(
        self,
        *,
        result: dict[str, Any],
        state: dict[str, Any],
        memory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metrics = build_metrics(
            identity=self.identity,
            result=result,
            state=state,
            memory=memory,
        )
        atomic_write_json(self.paths.run_metrics, metrics)
        return metrics
