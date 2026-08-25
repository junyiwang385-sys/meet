"""Single-request and whole-segment chunk/merge summary orchestration."""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass
from typing import Any

from .artifacts import atomic_write_json, load_json, sha256_file
from .chunking import (
    BudgetPolicy,
    ChunkingError,
    build_chunk_plan,
    estimate_message_tokens,
    messages_fit,
    partition_merge_items,
    resolve_chunk_segments,
    stable_hash,
)
from .llm import (
    LlmConfig,
    LlmRunError,
    PROMPT_VERSION,
    RkllmServerSession,
    build_chunk_messages,
    build_full_messages,
    build_merge_messages,
)
from .transcript import render_timeline
from .validation import SummaryValidationError, validate_llm_result


SUMMARY_ORCHESTRATION_VERSION = "summary-orchestration.v1"


@dataclass(frozen=True)
class SummaryRunConfig:
    llm: LlmConfig
    safety_tokens: int
    chars_per_token: float
    fixed_overhead_tokens: int
    overlap_segments: int
    resume: bool

    @property
    def budget(self) -> BudgetPolicy:
        return BudgetPolicy(
            ctx=self.llm.ctx,
            output_tokens=self.llm.max_tokens,
            safety_tokens=self.safety_tokens,
            chars_per_token=self.chars_per_token,
            fixed_overhead_tokens=self.fixed_overhead_tokens,
            overlap_segments=self.overlap_segments,
        )


def _request_fingerprint(
    *,
    request_kind: str,
    messages: list[dict[str, str]],
    config: SummaryRunConfig,
    model_identity: dict[str, Any],
) -> str:
    return stable_hash(
        {
            "version": SUMMARY_ORCHESTRATION_VERSION,
            "prompt_version": PROMPT_VERSION,
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
    segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    identity_path = request_dir / "request_identity.json"
    summary_path = request_dir / "validated_summary.json"
    validation_path = request_dir / "validation.json"
    status_path = request_dir / "status.json"
    if not all(path.is_file() for path in (identity_path, summary_path, validation_path, status_path)):
        return None
    try:
        identity = load_json(identity_path)
        status = load_json(status_path)
        summary = load_json(summary_path)
        quality = load_json(validation_path)
    except (OSError, json.JSONDecodeError):
        return None
    if identity.get("fingerprint") != fingerprint:
        return None
    expected_hashes = identity.get("artifact_sha256")
    if not isinstance(expected_hashes, dict):
        return None
    artifact_paths = {
        "final_json": request_dir / "final_json.txt",
        "validated_summary": summary_path,
        "validation": validation_path,
        "status": status_path,
    }
    if any(not path.is_file() for path in artifact_paths.values()):
        return None
    if any(expected_hashes.get(name) != sha256_file(path) for name, path in artifact_paths.items()):
        return None
    if status.get("finish_reason") != "stop" or status.get("context_truncated"):
        return None
    try:
        normalized, current_quality = validate_llm_result(
            json.dumps(summary, ensure_ascii=False),
            "stop",
            segments,
            context_truncated=False,
        )
    except SummaryValidationError:
        return None
    if normalized != summary or quality.get("status") != "pass":
        return None
    current_quality["warnings"].append("reused validated LLM artifact")
    return summary, current_quality


def _run_and_validate(
    session: RkllmServerSession,
    *,
    messages: list[dict[str, str]],
    request_dir: pathlib.Path,
    request_id: str,
    request_kind: str,
    segments: list[dict[str, Any]],
    config: SummaryRunConfig,
    model_identity: dict[str, Any],
    phase: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fingerprint = _request_fingerprint(
        request_kind=request_kind,
        messages=messages,
        config=config,
        model_identity=model_identity,
    )
    identity_path = request_dir / "request_identity.json"
    llm_result = session.request(
        messages,
        request_dir,
        max_tokens=config.llm.max_tokens,
        phase=phase,
        request_id=request_id,
    )
    summary, quality = validate_llm_result(
        llm_result["content"],
        llm_result["finish_reason"],
        segments,
        context_truncated=bool(llm_result["context_truncated"]),
    )
    summary_path = request_dir / "validated_summary.json"
    validation_path = request_dir / "validation.json"
    atomic_write_json(summary_path, summary)
    atomic_write_json(validation_path, quality)
    artifact_paths = {
        "final_json": request_dir / "final_json.txt",
        "validated_summary": summary_path,
        "validation": validation_path,
        "status": request_dir / "status.json",
    }
    atomic_write_json(
        identity_path,
        {
            "fingerprint": fingerprint,
            "request_kind": request_kind,
            "artifact_sha256": {
                name: sha256_file(path) for name, path in artifact_paths.items()
            },
        },
    )
    return summary, quality, llm_result


def _messages_for_chunk(
    chunk_segments: list[dict[str, Any]], chunk_id: str
) -> list[dict[str, str]]:
    timeline = render_timeline(chunk_segments)
    speakers = sorted({segment["speaker_id"] for segment in chunk_segments})
    return build_chunk_messages(
        timeline,
        speakers,
        chunk_id=chunk_id,
        coverage_start_ms=chunk_segments[0]["start_ms"],
        coverage_end_ms=chunk_segments[-1]["end_ms"],
    )


def _attempt_reuse(
    *,
    request_dir: pathlib.Path,
    messages: list[dict[str, str]],
    request_kind: str,
    segments: list[dict[str, Any]],
    config: SummaryRunConfig,
    model_identity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not config.resume:
        return None
    fingerprint = _request_fingerprint(
        request_kind=request_kind,
        messages=messages,
        config=config,
        model_identity=model_identity,
    )
    return _load_reusable_request(request_dir, fingerprint, segments)


def run_summary_stage(
    *,
    config: SummaryRunConfig,
    segments: list[dict[str, Any]],
    speaker_ids: list[str],
    timeline: str,
    out_dir: pathlib.Path,
    sampler: Any | None,
    model_identity: dict[str, Any],
) -> dict[str, Any]:
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = config.budget
    full_messages = build_full_messages(timeline, speaker_ids)
    full_estimate = estimate_message_tokens(full_messages, budget)
    plan: dict[str, Any] = {
        "version": SUMMARY_ORCHESTRATION_VERSION,
        "prompt_version": PROMPT_VERSION,
        "input_token_budget": budget.input_token_budget,
        "full_estimated_prompt_tokens": full_estimate,
        "full_request_fits": full_estimate <= budget.input_token_budget,
    }
    request_records: list[dict[str, Any]] = []
    reused_count = 0
    session: RkllmServerSession | None = None

    def ensure_session() -> RkllmServerSession:
        nonlocal session
        if session is None:
            session = RkllmServerSession(config.llm, out_dir, sampler)
            session.start()
        return session

    try:
        if messages_fit(full_messages, budget):
            request_dir = out_dir / "requests" / "full"
            reused = _attempt_reuse(
                request_dir=request_dir,
                messages=full_messages,
                request_kind="full",
                segments=segments,
                config=config,
                model_identity=model_identity,
            )
            if reused is not None:
                summary, quality = reused
                reused_count += 1
                plan["policy"] = "single_request_full_timeline"
                atomic_write_json(out_dir / "plan.json", plan)
                return _result(
                    summary=summary,
                    quality=quality,
                    policy=plan["policy"],
                    request_records=request_records,
                    reused_count=reused_count,
                    session=session,
                    started=started,
                    plan=plan,
                )
            try:
                summary, quality, llm_result = _run_and_validate(
                    ensure_session(),
                    messages=full_messages,
                    request_dir=request_dir,
                    request_id="full",
                    request_kind="full",
                    segments=segments,
                    config=config,
                    model_identity=model_identity,
                    phase="llm_summary_full",
                )
                request_records.append(_request_record(llm_result, full_estimate, "full"))
                plan["policy"] = "single_request_full_timeline"
                atomic_write_json(out_dir / "plan.json", plan)
                return _result(
                    summary=summary,
                    quality=quality,
                    policy=plan["policy"],
                    request_records=request_records,
                    reused_count=reused_count,
                    session=session,
                    started=started,
                    plan=plan,
                )
            except SummaryValidationError as exc:
                # Only an authoritative input truncation falls back to chunking.
                if "input truncation" not in str(exc):
                    raise
                plan["full_request_fallback_reason"] = str(exc)

        chunk_plan = build_chunk_plan(segments, budget, _messages_for_chunk)
        plan.update({"policy": "whole_segment_chunk_merge", "chunk_plan": chunk_plan})
        atomic_write_json(out_dir / "plan.json", plan)
        by_id = {segment["segment_id"]: segment for segment in segments}
        chunk_summaries: list[dict[str, Any]] = []
        for chunk in chunk_plan["chunks"]:
            chunk_segments = resolve_chunk_segments(segments, chunk)
            messages = _messages_for_chunk(chunk_segments, chunk["chunk_id"])
            request_dir = out_dir / "chunks" / chunk["chunk_id"]
            reused = _attempt_reuse(
                request_dir=request_dir,
                messages=messages,
                request_kind="chunk",
                segments=chunk_segments,
                config=config,
                model_identity=model_identity,
            )
            if reused is not None:
                summary, _ = reused
                reused_count += 1
            else:
                summary, _, llm_result = _run_and_validate(
                    ensure_session(),
                    messages=messages,
                    request_dir=request_dir,
                    request_id=chunk["chunk_id"],
                    request_kind="chunk",
                    segments=chunk_segments,
                    config=config,
                    model_identity=model_identity,
                    phase="llm_summary_chunk",
                )
                request_records.append(
                    _request_record(
                        llm_result, chunk["estimated_prompt_tokens"], chunk["chunk_id"]
                    )
                )
            chunk_summaries.append(summary)

        current = chunk_summaries
        round_number = 1
        merge_operation_count = 0
        merge_request_count = 0
        reused_merge_count = 0
        while len(current) > 1:
            groups = partition_merge_items(
                current,
                budget,
                lambda items, merge_id: build_merge_messages(items, merge_id=merge_id),
                round_number=round_number,
            )
            if len(groups) >= len(current):
                raise ChunkingError("merge plan cannot reduce summary count within context budget")
            next_round: list[dict[str, Any]] = []
            for group in groups:
                items = current[group["start_index"] : group["end_index"]]
                merge_id = group["merge_id"]
                messages = build_merge_messages(items, merge_id=merge_id)
                refs = _collect_refs(items)
                validation_segments = [by_id[ref] for ref in refs if ref in by_id]
                request_dir = out_dir / "merges" / f"round-{round_number:02d}" / merge_id
                reused = _attempt_reuse(
                    request_dir=request_dir,
                    messages=messages,
                    request_kind="merge",
                    segments=validation_segments,
                    config=config,
                    model_identity=model_identity,
                )
                if reused is not None:
                    summary, _ = reused
                    reused_count += 1
                    reused_merge_count += 1
                else:
                    summary, _, llm_result = _run_and_validate(
                        ensure_session(),
                        messages=messages,
                        request_dir=request_dir,
                        request_id=merge_id,
                        request_kind="merge",
                        segments=validation_segments,
                        config=config,
                        model_identity=model_identity,
                        phase="llm_summary_merge",
                    )
                    request_records.append(
                        _request_record(
                            llm_result, group["estimated_prompt_tokens"], merge_id
                        )
                    )
                    merge_request_count += 1
                next_round.append(summary)
                merge_operation_count += 1
            current = next_round
            round_number += 1
        summary = current[0]
        summary, quality = validate_llm_result(
            json.dumps(summary, ensure_ascii=False),
            "stop",
            segments,
            context_truncated=False,
        )
        quality["checks"]["full_meeting_coverage"] = chunk_plan["coverage_complete"]
        quality["checks"]["chunk_merge"] = True
        plan["merge_operation_count"] = merge_operation_count
        plan["merge_request_count"] = merge_request_count
        plan["reused_merge_count"] = reused_merge_count
        atomic_write_json(out_dir / "plan.json", plan)
        return _result(
            summary=summary,
            quality=quality,
            policy=plan["policy"],
            request_records=request_records,
            reused_count=reused_count,
            session=session,
            started=started,
            plan=plan,
        )
    finally:
        if session is not None:
            session.close()


def _collect_refs(summaries: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()

    def add(values: Any) -> None:
        if not isinstance(values, list):
            return
        for value in values:
            value = str(value)
            if value not in seen:
                seen.add(value)
                refs.append(value)

    for summary in summaries:
        overview = summary.get("overview")
        if isinstance(overview, dict):
            add(overview.get("refs"))
        for field in (
            "chapters",
            "speakers",
            "key_points",
            "decisions",
            "action_items",
            "open_questions",
            "risks",
            "keywords",
        ):
            for item in summary.get(field, []):
                if isinstance(item, dict):
                    add(item.get("refs"))
    return refs


def _request_record(
    llm_result: dict[str, Any], estimated_prompt_tokens: int, request_id: str
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "usage": llm_result.get("usage"),
        "timings": llm_result.get("timings"),
        "request_elapsed_seconds": llm_result.get("request_elapsed_seconds"),
        "thinking_source": llm_result.get("thinking_source"),
        "thinking_characters": len(llm_result.get("thinking") or ""),
        "context_truncated": llm_result.get("context_truncated"),
    }


def _result(
    *,
    summary: dict[str, Any],
    quality: dict[str, Any],
    policy: str,
    request_records: list[dict[str, Any]],
    reused_count: int,
    session: RkllmServerSession | None,
    started: float,
    plan: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "quality": quality,
        "policy": policy,
        "request_count": session.request_count if session is not None else 0,
        "validated_request_count": len(request_records),
        "reused_request_count": reused_count,
        "requests": request_records,
        "server_ready_seconds": session.ready_seconds if session is not None else None,
        "resolved_model_files": session.files if session is not None else None,
        "elapsed_seconds": round(time.time() - started, 3),
        "plan": plan,
    }
