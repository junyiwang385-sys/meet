"""Bounded error-report projection for one Harness run."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..contracts.errors import _jsonable, _safe_text, normalize_error
from ..contracts.identity import RunIdentity
from ..contracts.results import ERROR_REPORT_SCHEMA_VERSION


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_error_report(
    error: Any,
    *,
    identity: RunIdentity,
    paths: Any,
    result: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a small diagnostic report without embedding prompts or model output."""
    normalized = normalize_error(error)
    stage = normalized.get("stage")
    stages = state.get("stages", {}) if isinstance(state, dict) else {}
    stage_details = stages.get(stage) if isinstance(stages, dict) else None
    log_tail = None
    if isinstance(stage_details, dict) and isinstance(stage_details.get("log_tail"), str):
        log_tail = _safe_text(stage_details["log_tail"])

    return {
        "schema_version": ERROR_REPORT_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "identity": identity.as_dict(),
        "status": "failed",
        "error": normalized,
        "stage_details": _jsonable(stage_details) if isinstance(stage_details, dict) else None,
        "log_tail": log_tail,
        "diagnosis": {
            "agent_enabled": False,
            "inputs": {
                "run_manifest": str(paths.run_manifest.relative_to(paths.root)),
                "run_events": str(paths.run_events.relative_to(paths.root)),
                "stage_status": str(paths.stage_status.relative_to(paths.root)),
                "error_report": str(paths.error_report.relative_to(paths.root)),
            },
        },
        "result_status": result.get("status") if isinstance(result, dict) else None,
    }
