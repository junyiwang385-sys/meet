"""Stable error categories, normalization, and retry semantics."""

from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

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
