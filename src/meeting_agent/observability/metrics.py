"""Run-level metrics projection."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..contracts.errors import _jsonable
from ..contracts.identity import RunIdentity
from ..contracts.results import RUN_METRICS_SCHEMA_VERSION


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_metrics(
    *,
    identity: RunIdentity,
    result: dict[str, Any],
    state: dict[str, Any],
    memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact, deterministic summary of one Harness run."""
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

    return {
        "schema_version": RUN_METRICS_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "identity": identity.as_dict(),
        "status": result.get("status"),
        "total_elapsed_seconds": runtime.get("total_elapsed_seconds"),
        "stage_counts": stage_counts,
        "stage_elapsed_seconds": stage_elapsed_seconds,
        "llm": _jsonable(runtime.get("llm") or {}),
        "memory": _jsonable(memory or runtime.get("memory") or {}),
        "error_count": len(result.get("errors") or []) if isinstance(result.get("errors"), list) else 0,
        "artifact_count": len(result.get("artifacts") or {}) if isinstance(result.get("artifacts"), dict) else 0,
    }
