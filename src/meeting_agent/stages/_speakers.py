"""发言人文档：分组、按预算截断、装箱成批。从 product_summary.py 拆出。

发言人总结是 best-effort 增强：只给"实质发言"的人出、跳过 unknown 与琐碎发言，
并把多个发言人装进能塞下的 batch（不依赖发言顺序）。
"""

from __future__ import annotations

from typing import Any

from ..llm.chunking import BudgetPolicy, ChunkingError, estimate_message_tokens
from .transcript import render_timeline
from ._prompts import _speaker_batch_messages


SPEAKER_MIN_CHARS = 80
def _build_speaker_documents(
    segments: list[dict[str, Any]],
    *,
    min_chars: int = SPEAKER_MIN_CHARS,
) -> list[dict[str, Any]]:
    """按 speaker 分组非空段；跳过 unknown，并过滤实质发言不足的 speaker。

    发言人总结是 best-effort 增强，不给 unknown 和只说了几句话的人硬出总结
    （避免 diarization 噪声与"该发言人主要进行了简短确认"式填充）。
    """
    documents: dict[str, dict[str, Any]] = {}
    for segment in segments:
        speaker_id = str(segment["speaker_id"])
        if speaker_id == "unknown":
            continue
        document = documents.setdefault(
            speaker_id,
            {
                "speaker_id": speaker_id,
                "segments": [],
                "first_index": int(segment.get("index", len(documents))),
            },
        )
        document["segments"].append(segment)
    return [
        document
        for document in documents.values()
        if sum(len(str(s.get("text") or "")) for s in document["segments"]) >= min_chars
    ]
def _truncate_speaker_document_to_budget(
    document: dict[str, Any],
    budget: BudgetPolicy,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Keep the longest chronological prefix that fits the speaker budget."""
    full_estimate = estimate_message_tokens(
        _speaker_batch_messages([document], ref_map=ref_map, speaker_map=speaker_map),
        budget,
    )
    if full_estimate <= budget.input_token_budget:
        return document, None

    original_segments = list(document["segments"])

    def estimate_segments(candidate_segments: list[dict[str, Any]]) -> int:
        candidate = {**document, "segments": candidate_segments}
        return estimate_message_tokens(
            _speaker_batch_messages([candidate], ref_map=ref_map, speaker_map=speaker_map),
            budget,
        )

    low = 0
    high = len(original_segments)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_segments(original_segments[:middle]) <= budget.input_token_budget:
            low = middle
        else:
            high = middle - 1

    retained_segments = list(original_segments[:low])
    if low < len(original_segments):
        next_segment = original_segments[low]
        original_text = str(next_segment.get("text") or "")
        text_low = 0
        text_high = len(original_text)
        best_text = ""
        while text_low <= text_high:
            middle = (text_low + text_high) // 2
            partial_segment = {**next_segment, "text": original_text[:middle]}
            candidate_segments = [*retained_segments, partial_segment]
            if estimate_segments(candidate_segments) <= budget.input_token_budget:
                best_text = original_text[:middle]
                text_low = middle + 1
            else:
                text_high = middle - 1
        if best_text:
            retained_segments.append({**next_segment, "text": best_text})

    if not retained_segments:
        raise ChunkingError(
            f"speaker_prompt_overhead_exceeds_budget: {document['speaker_id']}"
        )

    retained_document = {
        **document,
        "segments": retained_segments,
        "_truncation": {
            "original_segment_count": len(original_segments),
            "retained_segment_count": len(retained_segments),
            "original_text_chars": sum(len(str(item.get("text") or "")) for item in original_segments),
            "retained_text_chars": sum(len(str(item.get("text") or "")) for item in retained_segments),
            "original_estimated_prompt_tokens": full_estimate,
            "retained_estimated_prompt_tokens": estimate_segments(retained_segments),
        },
    }
    return retained_document, retained_document["_truncation"]
def _truncate_speaker_documents(
    documents: list[dict[str, Any]],
    budget: BudgetPolicy,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    truncated_documents = []
    truncations = []
    for document in documents:
        retained, record = _truncate_speaker_document_to_budget(
            document,
            budget,
            ref_map=ref_map,
            speaker_map=speaker_map,
        )
        truncated_documents.append(retained)
        if record is not None:
            truncations.append({"speaker_id": document["speaker_id"], **record})
    return truncated_documents, truncations
def _pack_speaker_documents(
    documents: list[dict[str, Any]],
    budget: BudgetPolicy,
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
) -> list[list[dict[str, Any]]]:
    """Pack speakers into budget-fitting batches without relying on speaker order."""
    ordered = sorted(
        documents,
        key=lambda item: (-len(render_timeline(item["segments"])), item["first_index"]),
    )
    batches: list[list[dict[str, Any]]] = []
    estimates: list[int] = []
    for document in ordered:
        best_index = None
        best_remaining = None
        for index, batch in enumerate(batches):
            candidate = [*batch, document]
            estimate = estimate_message_tokens(_speaker_batch_messages(candidate, ref_map=ref_map, speaker_map=speaker_map), budget)
            if estimate > budget.input_token_budget:
                continue
            remaining = budget.input_token_budget - estimate
            if best_remaining is None or remaining < best_remaining:
                best_index = index
                best_remaining = remaining
        if best_index is None:
            estimate = estimate_message_tokens(_speaker_batch_messages([document], ref_map=ref_map, speaker_map=speaker_map), budget)
            if estimate > budget.input_token_budget:
                raise ChunkingError(
                    f"speaker_exceeds_speaker_batch_budget: {document['speaker_id']}"
                )
            batches.append([document])
            estimates.append(estimate)
        else:
            batches[best_index].append(document)
            estimates[best_index] = estimate_message_tokens(
                _speaker_batch_messages(batches[best_index]), budget
            )
    batches.sort(key=lambda batch: min(item["first_index"] for item in batch))
    return batches
