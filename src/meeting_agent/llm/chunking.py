"""Deterministic prompt budgeting and whole-segment chunk planning."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Callable

from ..stages.transcript import render_timeline


CHUNKING_VERSION = "whole-segment.v1"


class ChunkingError(ValueError):
    pass


@dataclass(frozen=True)
class BudgetPolicy:
    ctx: int
    output_tokens: int
    safety_tokens: int = 512
    chars_per_token: float = 1.3
    fixed_overhead_tokens: int = 128
    overlap_segments: int = 1

    @property
    def input_token_budget(self) -> int:
        budget = self.ctx - self.output_tokens - self.safety_tokens
        if budget <= 0:
            raise ChunkingError("ctx is too small after output and safety token reserves")
        return budget


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def estimate_text_tokens(text: str, policy: BudgetPolicy) -> int:
    if policy.chars_per_token <= 0:
        raise ChunkingError("chars_per_token must be positive")
    return math.ceil(len(text) / policy.chars_per_token) + policy.fixed_overhead_tokens


def estimate_message_tokens(messages: list[dict[str, str]], policy: BudgetPolicy) -> int:
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return estimate_text_tokens(serialized, policy)


def messages_fit(messages: list[dict[str, str]], policy: BudgetPolicy) -> bool:
    return estimate_message_tokens(messages, policy) <= policy.input_token_budget


def build_chunk_plan(
    segments: list[dict[str, Any]],
    policy: BudgetPolicy,
    message_builder: Callable[[list[dict[str, Any]], str], list[dict[str, str]]],
) -> dict[str, Any]:
    nonempty = [segment for segment in segments if segment.get("text")]
    if not nonempty:
        return {
            "version": CHUNKING_VERSION,
            "policy": _policy_dict(policy),
            "chunks": [],
            "nonempty_segment_count": 0,
            "coverage_complete": True,
        }

    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(nonempty):
        chunk_number = len(chunks) + 1
        chunk_id = f"chunk-{chunk_number:06d}"
        end = start
        last_fit = None
        while end < len(nonempty):
            preferred_context_start = max(0, start - policy.overlap_segments)
            candidate_fit = None
            for context_start in range(preferred_context_start, start + 1):
                provided = nonempty[context_start : end + 1]
                messages = message_builder(provided, chunk_id)
                estimate = estimate_message_tokens(messages, policy)
                if estimate <= policy.input_token_budget:
                    candidate_fit = (end + 1, context_start, provided, estimate)
                    break
            if candidate_fit is None:
                break
            last_fit = candidate_fit
            end += 1
        if last_fit is None:
            segment = nonempty[start]
            raise ChunkingError(
                "segment_exceeds_chunk_budget: "
                f"{segment['segment_id']} cannot fit input budget {policy.input_token_budget}"
            )
        next_start, context_start, provided, estimate = last_fit
        main_segments = nonempty[start:next_start]
        chunks.append(
            {
                "chunk_id": chunk_id,
                "main_segment_ids": [item["segment_id"] for item in main_segments],
                "context_segment_ids": [item["segment_id"] for item in provided[: start - context_start]],
                "provided_segment_ids": [item["segment_id"] for item in provided],
                "coverage_start_ms": main_segments[0]["start_ms"],
                "coverage_end_ms": main_segments[-1]["end_ms"],
                "estimated_prompt_tokens": estimate,
                "input_token_budget": policy.input_token_budget,
                "segment_hash": stable_hash(provided),
            }
        )
        start = next_start

    covered = [segment_id for chunk in chunks for segment_id in chunk["main_segment_ids"]]
    expected = [segment["segment_id"] for segment in nonempty]
    plan = {
        "version": CHUNKING_VERSION,
        "policy": _policy_dict(policy),
        "chunks": chunks,
        "nonempty_segment_count": len(nonempty),
        "coverage_complete": covered == expected,
        "covered_segment_ids": covered,
    }
    plan["plan_hash"] = stable_hash(plan)
    return plan


def resolve_chunk_segments(
    segments: list[dict[str, Any]], chunk: dict[str, Any]
) -> list[dict[str, Any]]:
    by_id = {segment["segment_id"]: segment for segment in segments}
    try:
        return [by_id[segment_id] for segment_id in chunk["provided_segment_ids"]]
    except KeyError as exc:
        raise ChunkingError(f"chunk references missing segment: {exc.args[0]}") from exc


def partition_merge_items(
    items: list[dict[str, Any]],
    policy: BudgetPolicy,
    message_builder: Callable[[list[dict[str, Any]], str], list[dict[str, str]]],
    *,
    round_number: int,
) -> list[dict[str, Any]]:
    if not items:
        raise ChunkingError("cannot merge an empty item list")
    groups = []
    start = 0
    while start < len(items):
        group_number = len(groups) + 1
        merge_id = f"merge-r{round_number:02d}-g{group_number:04d}"
        end = start
        last_fit = None
        while end < len(items):
            candidate = items[start : end + 1]
            estimate = estimate_message_tokens(message_builder(candidate, merge_id), policy)
            if estimate > policy.input_token_budget:
                break
            last_fit = (end + 1, estimate)
            end += 1
        if last_fit is None:
            raise ChunkingError(
                f"merge_item_exceeds_budget: item {start} cannot fit {policy.input_token_budget}"
            )
        next_start, estimate = last_fit
        groups.append(
            {
                "merge_id": merge_id,
                "start_index": start,
                "end_index": next_start,
                "estimated_prompt_tokens": estimate,
                "item_hashes": [stable_hash(item) for item in items[start:next_start]],
            }
        )
        start = next_start
    return groups


def _policy_dict(policy: BudgetPolicy) -> dict[str, Any]:
    return {
        "ctx": policy.ctx,
        "output_tokens": policy.output_tokens,
        "safety_tokens": policy.safety_tokens,
        "chars_per_token": policy.chars_per_token,
        "fixed_overhead_tokens": policy.fixed_overhead_tokens,
        "overlap_segments": policy.overlap_segments,
        "input_token_budget": policy.input_token_budget,
    }
