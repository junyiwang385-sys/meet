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
from ..llm.llm import LlmRunError
from ._prompts import _build_retry_messages
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


class _RequestRunner:
    """一次 LLM 请求的编排：断点复用 → 发送 → 业务校验 → 受控重试（≤1 次）→ 落盘复用凭证。

    从 run_product_summary_stage 的 run_request 闭包提出。计数器（reused/validation_failed/
    retry）与 request_records/request_attempts 由本对象持有，调用方读 runner.* 汇总。
    session 通过注入的 ensure_session/model_identity 回调获取（stage 持有 server 生命周期）。
    """

    def __init__(
        self,
        *,
        config: Any,
        run_log: Any,
        ensure_session: Callable[[], Any],
        model_identity: Callable[[], dict[str, Any]],
    ) -> None:
        self.config = config
        self.run_log = run_log
        self._ensure_session = ensure_session
        self._model_identity = model_identity
        self.reused_count = 0
        self.validation_failed_count = 0
        self.retry_count = 0
        self.request_records: list[dict[str, Any]] = []
        self.request_attempts: list[dict[str, Any]] = []

    def run(
        self,
        *,
        messages: list[dict[str, str]],
        request_dir: pathlib.Path,
        request_id: str,
        request_kind: str,
        phase: str,
        estimate: int,
        validator: Callable[[str, Any, bool], Any],
        quality_builder: Callable[[Any], dict[str, Any]] | None = None,
    ) -> Any:
        fingerprint = _request_fingerprint(
            request_kind=request_kind,
            messages=messages,
            config=self.config,
            model_identity=self._model_identity(),
        )
        if self.config.resume:
            reused = _load_reusable_request(request_dir, fingerprint, validator)
            if reused is not None:
                self.reused_count += 1
                _emit_run_log(
                    self.run_log,
                    "request_reused",
                    stage=phase,
                    message="复用已校验的 LLM 请求产物",
                    request={
                        "request_id": request_id,
                        "request_kind": request_kind,
                        "attempt": 0,
                        "estimated_prompt_tokens": estimate,
                    },
                    details={"request_dir": request_dir.name},
                )
                return reused
        think = _kind_uses_think(request_kind)
        kind_max_tokens = _kind_output_tokens(request_kind, self.config)
        request_messages = messages
        result = None
        validated = None
        for attempt in range(2):
            attempt_dir = request_dir if attempt == 0 else request_dir / f"attempt-{attempt + 1}"
            attempt_request_id = request_id if attempt == 0 else f"{request_id}-attempt-{attempt + 1}"
            try:
                result = self._ensure_session().request(
                    _apply_think_directive(request_messages, think),
                    attempt_dir,
                    max_tokens=kind_max_tokens,
                    phase=phase,
                    request_id=attempt_request_id,
                    request_kind=request_kind,
                    attempt=attempt + 1,
                    estimated_prompt_tokens=estimate,
                    run_log=self.run_log,
                )
            except LlmRunError as exc:
                self.request_attempts.append({
                    "request_id": attempt_request_id,
                    "request_kind": request_kind,
                    "attempt": attempt + 1,
                    "estimated_prompt_tokens": estimate,
                    "status": "request_failed",
                    "error_code": "request_failed",
                    "error_message": str(exc)[:600],
                })
                raise
            attempt_record = {
                **_request_record(result, estimate),
                "request_kind": request_kind,
                "attempt": attempt + 1,
                "status": "response_received",
            }
            self.request_attempts.append(attempt_record)
            try:
                validated = validator(
                    result["content"],
                    result["finish_reason"],
                    bool(result["context_truncated"]),
                )
                attempt_record["status"] = "validated"
                _emit_run_log(
                    self.run_log,
                    "validation_succeeded",
                    stage=phase,
                    message="LLM 业务校验通过",
                    request={
                        **_request_record(result, estimate),
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                    },
                )
                break
            except SummaryValidationError as exc:
                message = str(exc)
                failure_cause = (
                    "finish_reason_length"
                    if "finish_reason" in message and "length" in message
                    else "context_truncated"
                    if "input was truncated" in message
                    else "invalid_json"
                    if "not valid JSON" in message
                    else "missing_speaker_summaries"
                    if "missing speaker summaries" in message
                    else "validation_failed"
                )
                self.validation_failed_count += 1
                attempt_record["status"] = "validation_failed"
                attempt_record["error_code"] = "validation_failed"
                attempt_record["cause"] = failure_cause
                _emit_run_log(
                    self.run_log,
                    "validation_failed",
                    stage=phase,
                    level="error",
                    message="LLM 业务校验失败",
                    request={
                        **_request_record(result, estimate),
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                    },
                    error={
                        "stage": phase,
                        "code": "validation_failed",
                        "message": message,
                        "cause": failure_cause,
                        "request_id": attempt_request_id,
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                        "finish_reason": result.get("finish_reason"),
                        "context_truncated": result.get("context_truncated"),
                        "usage": result.get("usage"),
                        "request_elapsed_seconds": result.get("request_elapsed_seconds"),
                    },
                )
                retry_json = "LLM content is not valid JSON" in message
                retry_missing_speakers = "missing speaker summaries" in message
                retry_output_length = (
                    request_kind == "speaker-batch"
                    and "finish_reason" in message
                    and "length" in message
                )
                retry_context_truncated = "input was truncated" in message
                retry_too_short = "too short" in message
                if attempt != 0 or not (
                    retry_json
                    or retry_missing_speakers
                    or retry_output_length
                    or retry_context_truncated
                    or retry_too_short
                ):
                    raise
                if retry_too_short:
                    correction = (
                        "上一条摘要过短。请重新完整输出 JSON，把 summary/overview 写得更充实，"
                        "覆盖背景或问题、关键事实或方案、结论及影响，约 150 个汉字以上；"
                        "只依据输入内容，不要解释、不要额外字段、不要输出 markdown。"
                    )
                elif retry_output_length:
                    correction = (
                        "上一条响应达到输出长度上限。请重新完整输出 JSON，严格只保留 speakers 字段；"
                        "每个 speaker 只输出一条 overview，overview 控制在 40 个汉字以内，"
                        "refs 每条最多 3 个，只使用输入中对应 speaker 的 refs；"
                        "不要解释、不要输出额外字段、不要输出 markdown，必须在本次响应内闭合 JSON。"
                    )
                elif retry_context_truncated:
                    correction = (
                        "上一条请求的输入上下文被截断。请只根据本次完整输入输出 JSON，"
                        "每个 speaker 一条简短 overview，refs 每条最多 3 个，不要解释或额外字段。"
                    )
                elif retry_missing_speakers:
                    correction = (
                        "上一条输出遗漏了一个或多个 speaker 的总结。请重新完整输出当前请求的 JSON，"
                        "本批次输入中的每个 speaker_id 都必须各输出一条 speakers 项，"
                        "即使内容是简短回应或确认，也要给出基于原文的简短客观总结，"
                        "并为每条总结提供属于该 speaker 的 refs；不要省略任何 speaker。"
                    )
                else:
                    correction = (
                        "上一条输出不是可解析的 JSON。请重新完整输出当前请求的 JSON，"
                        "不要输出解释，不要截断，不要在字符串中放入未转义的换行或制表符；"
                        "每个章节最多输出 3 个 key_refs。"
                    )
                correction = (
                    f"{correction}\n"
                    f"校验反馈（程序自动判定，含实测数值）：{message}\n"
                    "上一条 assistant 内容就是你上次的输出，请在它的问题基础上直接改正，"
                    "不要重复同样的结果。"
                )
                self.retry_count += 1
                request_messages, echo = _build_retry_messages(
                    messages, result.get("content"), correction
                )
                _emit_run_log(
                    self.run_log,
                    "retry_requested",
                    stage=phase,
                    message="LLM 请求将进行受控重试",
                    request={
                        "request_id": attempt_request_id,
                        "request_kind": request_kind,
                        "attempt": attempt + 1,
                        "finish_reason": result.get("finish_reason"),
                        "context_truncated": result.get("context_truncated"),
                    },
                    details={
                        "cause": failure_cause,
                        "feedback": message[:200],
                        "echoed_previous_chars": len(echo),
                    },
                )
        assert result is not None
        assert validated is not None
        quality = quality_builder(validated) if quality_builder is not None else {"status": "pass"}
        _save_reusable_request(
            request_dir,
            fingerprint=fingerprint,
            request_kind=request_kind,
            validated=validated,
            quality=quality,
        )
        self.request_records.append(_request_record(result, estimate))
        return validated
