"""请求层助手：think 开关、请求记录/日志、模型身份、指纹与断点复用（resume）。

从 product_summary.py 拆出。这些是"围绕单次 LLM 请求"的确定性工具，不含发送本身
（发送在 RkllmServerSession.request；编排在 run_product_summary_stage）。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Callable

from ..storage.artifacts import atomic_write_json, load_json, sha256_file
from ..llm.chunking import stable_hash
from .validation import SummaryValidationError


PRODUCT_SUMMARY_VERSION = "product-summary.v25"
_THINK_KINDS = {"action-review"}
_KIND_OUTPUT_TOKENS = {
    "block-summary": 1200,
    "full-summary": 1400,
    "speaker-batch": 1400,
    "action-review": 3072,
    "full": 3072,
}
def _kind_uses_think(request_kind: str) -> bool:
    return request_kind in _THINK_KINDS
def _kind_output_tokens(request_kind: str, config: "ProductSummaryConfig") -> int:
    return min(
        _KIND_OUTPUT_TOKENS.get(request_kind, config.llm.max_tokens),
        config.llm.max_tokens,
    )
def _apply_think_directive(
    messages: list[dict[str, str]], think: bool
) -> list[dict[str, str]]:
    """think 关闭时在最后一条 user 内容尾部追加 Qwen3 的 /no_think 软开关。"""
    if think:
        return messages
    patched = [dict(message) for message in messages]
    for message in reversed(patched):
        if message.get("role") == "user":
            content = str(message.get("content") or "")
            if "/no_think" not in content:
                message["content"] = content + "\n/no_think"
            break
    return patched
def _request_record(result: dict[str, Any], estimate: int) -> dict[str, Any]:
    return {
        "request_id": result.get("request_id"),
        "estimated_prompt_tokens": estimate,
        "usage": result.get("usage"),
        "timings": result.get("timings"),
        "thinking_characters": len(result.get("thinking") or ""),
        "context_truncated": result.get("context_truncated"),
        "finish_reason": result.get("finish_reason"),
        "request_elapsed_seconds": result.get("request_elapsed_seconds"),
    }
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
    """Write bounded business events without making logging part of control flow."""

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
            source="product_summary",
        )
    except (OSError, TypeError, ValueError):
        return
def _model_identity(files: dict[str, Any]) -> dict[str, Any]:
    identity = {}
    for name, value in sorted(files.items()):
        path = pathlib.Path(str(value))
        item: dict[str, Any] = {"path": str(path)}
        if path.is_file():
            item.update({"size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
        identity[name] = item
    return identity
def _request_fingerprint(
    *,
    request_kind: str,
    messages: list[dict[str, str]],
    config: ProductSummaryConfig,
    model_identity: dict[str, Any],
) -> str:
    return stable_hash(
        {
            "version": PRODUCT_SUMMARY_VERSION,
            "request_kind": request_kind,
            "messages": messages,
            "ctx": config.llm.ctx,
            "predict": config.llm.predict,
            "max_tokens": config.llm.max_tokens,
            "temperature": config.llm.temperature,
            "model_identity": model_identity,
        }
    )
def _load_reusable_request(
    request_dir: pathlib.Path,
    fingerprint: str,
    validator: Callable[[str, Any, bool], Any],
) -> Any | None:
    identity_path = request_dir / "request_identity.json"
    status_path = request_dir / "status.json"
    final_path = request_dir / "final_json.txt"
    validated_path = request_dir / "validated_result.json"
    validation_path = request_dir / "validation.json"
    paths = {
        "final_json": final_path,
        "validated_result": validated_path,
        "validation": validation_path,
        "status": status_path,
    }
    if not identity_path.is_file() or any(not path.is_file() for path in paths.values()):
        return None
    try:
        identity = load_json(identity_path)
        status = load_json(status_path)
        validated = load_json(validated_path)
        quality = load_json(validation_path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if identity.get("fingerprint") != fingerprint:
        return None
    expected_hashes = identity.get("artifact_sha256")
    if not isinstance(expected_hashes, dict):
        return None
    if any(expected_hashes.get(name) != sha256_file(path) for name, path in paths.items()):
        return None
    if status.get("finish_reason") != "stop" or status.get("context_truncated"):
        return None
    if not isinstance(quality, dict) or quality.get("status") != "pass":
        return None
    try:
        current = validator(final_path.read_text(encoding="utf-8"), "stop", False)
    except (OSError, SummaryValidationError, KeyError, TypeError, ValueError):
        return None
    if current != validated:
        return None
    return current
def _save_reusable_request(
    request_dir: pathlib.Path,
    *,
    fingerprint: str,
    request_kind: str,
    validated: Any,
    quality: dict[str, Any],
) -> None:
    validated_path = request_dir / "validated_result.json"
    validation_path = request_dir / "validation.json"
    atomic_write_json(validated_path, validated)
    atomic_write_json(validation_path, quality)
    paths = {
        "final_json": request_dir / "final_json.txt",
        "validated_result": validated_path,
        "validation": validation_path,
        "status": request_dir / "status.json",
    }
    atomic_write_json(
        request_dir / "request_identity.json",
        {
            "fingerprint": fingerprint,
            "request_kind": request_kind,
            "artifact_sha256": {name: sha256_file(path) for name, path in paths.items()},
        },
    )
