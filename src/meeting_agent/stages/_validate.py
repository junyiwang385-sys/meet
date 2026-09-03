"""摘要输出的校验/归一/修复：块摘要、核心章节区间、overview、待办、发言人批次等。

从 product_summary.py 拆出。全部是"对模型输出做确定性校验与降级"的纯函数。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..llm.chunking import BudgetPolicy, estimate_message_tokens, messages_fit
from .summary_profiles import DomainProfile, GENERIC_PROFILE
from .transcript import render_timeline
from .validation import (
    SummaryValidationError,
    clean_text,
    parse_content,
    validate_summary_object,
)
from ._refmap import (
    _build_compact_ref_map,
    _build_compact_speaker_map,
    _compactize_payload,
    _expand_payload,
)
from ._prompts import (
    ACTION_REVIEW_SHAPE,
    BLOCK_SUMMARY_SHAPE,
    FULL_MEETING_SHAPE,
    FULL_SUMMARY_SHAPE,
    SPEAKER_BATCH_SHAPE,
)

# 发言人总结 refs：每人从自己最长段里指派这么多条（由校验/指派逻辑使用）
SPEAKER_REFS_PER_SPEAKER = 2


MIN_OVERVIEW_CHARS = 120
def _validate_speaker_batch(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    documents: list[dict[str, Any]],
    *,
    ref_map: dict[str, str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"speaker batch finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("speaker batch input was truncated")
    raw = parse_content(content)
    batch_segments = [segment for document in documents for segment in document["segments"]]
    if ref_map is None:
        ref_map, _ = _build_compact_ref_map(batch_segments)
    if speaker_map is None:
        speaker_map, _ = _build_compact_speaker_map(
            [document["speaker_id"] for document in documents]
        )
    compact_speaker_map = {compact: canonical for canonical, compact in speaker_map.items()}
    raw = _expand_payload(raw, {}, compact_speaker_map)
    raw_speakers = raw.get("speakers", [])
    if not isinstance(raw_speakers, list):
        raise SummaryValidationError("speakers must be an array")
    # 模型只提供 overview 文本；refs 由代码从该 speaker 自己的段落指派，杜绝编造证据。
    overview_by_speaker: dict[str, str] = {}
    for item in raw_speakers:
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker_id") or "")
        overview = clean_text(item.get("overview"))
        if speaker_id and overview is not None and speaker_id not in overview_by_speaker:
            overview_by_speaker[speaker_id] = overview
    results = []
    for document in documents:
        speaker_id = document["speaker_id"]
        overview = overview_by_speaker.get(speaker_id)
        if overview is None:
            # best-effort：模型没给这条就跳过，绝不因缺 speaker 而使整条 pipeline 失败。
            continue
        own = sorted(
            (s for s in document["segments"] if s.get("text")),
            key=lambda s: len(str(s["text"])),
            reverse=True,
        )
        refs = [s["segment_id"] for s in own[:SPEAKER_REFS_PER_SPEAKER]]
        if not refs:
            continue
        results.append({"speaker_id": speaker_id, "overview": overview, "refs": refs})
    return results
def _normalize_overlapping_core_candidates(
    candidates: list[dict[str, Any]],
    repairs: list[dict[str, Any]],
    *,
    location_prefix: str,
) -> list[dict[str, Any]]:
    """Make model chapter intervals deterministic before range expansion."""
    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda item: (item["start_pos"], item["end_pos"], item.get("index", 0)),
    )
    normalized: list[dict[str, Any]] = []
    for current in ordered:
        start_pos = current["start_pos"]
        end_pos = current["end_pos"]
        if end_pos < start_pos:
            repairs.append(
                {
                    "type": "normalize_reversed_core_chapter_range",
                    "location": f"{location_prefix}[{current.get('index', len(normalized))}]",
                    "old_start_pos": start_pos,
                    "old_end_pos": end_pos,
                }
            )
            current["end_pos"] = start_pos
            end_pos = start_pos
        if normalized:
            previous = normalized[-1]
            previous_start = previous["start_pos"]
            previous_end = previous["end_pos"]
            if start_pos == previous_start:
                previous["end_pos"] = max(previous_end, end_pos)
                for refs_key in ("key_refs", "refs"):
                    previous_refs = previous.get(refs_key)
                    current_refs = current.get(refs_key)
                    if isinstance(previous_refs, list) and isinstance(current_refs, list):
                        previous[refs_key] = list(dict.fromkeys(previous_refs + current_refs))
                for text_key in ("title", "overview", "summary"):
                    previous_text = previous.get(text_key)
                    current_text = current.get(text_key)
                    if (
                        isinstance(previous_text, str)
                        and isinstance(current_text, str)
                        and current_text
                        and current_text != previous_text
                    ):
                        previous[text_key] = f"{previous_text}；{current_text}"
                repairs.append(
                    {
                        "type": "merge_same_start_core_chapters",
                        "location": f"{location_prefix}[{current.get('index', len(normalized))}]",
                        "start_pos": start_pos,
                    }
                )
                continue
            if start_pos <= previous_end:
                new_previous_end = start_pos - 1
                repairs.append(
                    {
                        "type": "clip_overlapping_core_chapter_boundary",
                        "location": f"{location_prefix}[{len(normalized) - 1}]",
                        "old_end_pos": previous_end,
                        "new_end_pos": new_previous_end,
                        "next_start_pos": start_pos,
                    }
                )
                previous["end_pos"] = new_previous_end
        normalized.append(current)
    return normalized
def _expand_core_chapter_ranges(
    core_chapters: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    *,
    coverage_end_ref: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not core_chapters:
        raise SummaryValidationError("LLM returned no completed core chapters")
    positions = {segment["segment_id"]: index for index, segment in enumerate(segments)}
    if coverage_end_ref not in positions:
        raise SummaryValidationError("chapter coverage end is outside current input")
    coverage_end_pos = positions[coverage_end_ref]
    repairs = []
    range_candidates = [
        {
            **chapter,
            "start_pos": positions[chapter["core_start_ref"]],
            "end_pos": positions[chapter["core_end_ref"]],
        }
        for chapter in core_chapters
    ]
    ordered = _normalize_overlapping_core_candidates(
        range_candidates,
        repairs,
        location_prefix="chapters",
    )
    expanded = []
    for index, chapter in enumerate(ordered):
        core_start_pos = chapter["start_pos"]
        core_end_pos = min(chapter["end_pos"], coverage_end_pos)
        core_start_ref = segments[core_start_pos]["segment_id"]
        core_end_ref = segments[core_end_pos]["segment_id"]
        if index + 1 < len(ordered):
            next_start_pos = ordered[index + 1]["start_pos"]
            full_end_pos = min(next_start_pos - 1, coverage_end_pos)
        else:
            full_end_pos = coverage_end_pos
        full_start_pos = 0 if index == 0 else core_start_pos
        if full_start_pos > full_end_pos:
            repairs.append(
                {
                    "type": "drop_empty_core_chapter_after_boundary_repair",
                    "location": f"chapters[{index}]",
                    "core_start_ref": core_start_ref,
                    "core_end_ref": core_end_ref,
                }
            )
            continue
        if core_end_pos < core_start_pos:
            core_end_pos = core_start_pos
            core_end_ref = segments[core_end_pos]["segment_id"]
        if core_end_pos > full_end_pos:
            core_end_pos = full_end_pos
            core_end_ref = segments[core_end_pos]["segment_id"]
            repairs.append(
                {
                    "type": "clip_core_chapter_to_continuous_boundary",
                    "location": f"chapters[{index}]",
                    "new_core_end_ref": core_end_ref,
                }
            )
        full_start_ref = segments[full_start_pos]["segment_id"]
        full_end_ref = segments[full_end_pos]["segment_id"]
        expanded_chapter = {
            key: value
            for key, value in chapter.items()
            if key not in {"start_pos", "end_pos"}
        }
        expanded_chapter.update(
            {
                "core_start_ref": core_start_ref,
                "core_end_ref": core_end_ref,
                "start_ref": full_start_ref,
                "end_ref": full_end_ref,
                "start_ms": segments[full_start_pos]["start_ms"],
                "end_ms": segments[full_end_pos]["end_ms"],
            }
        )
        expanded.append(expanded_chapter)
        if full_start_ref != core_start_ref or full_end_ref != core_end_ref:
            repairs.append(
                {
                    "type": "expand_core_chapter_to_continuous_range",
                    "location": f"chapters[{index}]",
                    "core_start_ref": core_start_ref,
                    "core_end_ref": core_end_ref,
                    "start_ref": full_start_ref,
                    "end_ref": full_end_ref,
                }
            )
    return expanded, repairs
def _validate_full_core_result(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"full summary finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("full summary input was truncated")
    raw = parse_content(content)
    ref_map, compact_ref_map = _build_compact_ref_map(segments)
    speaker_map, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in segments]
    )
    raw = _expand_payload(raw, compact_ref_map, compact_speaker_map)
    raw_chapters = raw.get("chapters")
    if not isinstance(raw_chapters, list):
        raise SummaryValidationError("chapters must be an array")
    positions = {segment["segment_id"]: index for index, segment in enumerate(segments)}
    prepared_chapters = []
    pre_repairs = []
    for index, chapter in enumerate(raw_chapters):
        if not isinstance(chapter, dict):
            raise SummaryValidationError(f"chapters[{index}] must be an object")
        core_start_ref = str(
            chapter.get("core_start_ref") or chapter.get("start_ref") or ""
        )
        core_end_ref = str(
            chapter.get("core_end_ref") or chapter.get("end_ref") or ""
        )
        if core_start_ref not in positions or core_end_ref not in positions:
            raise SummaryValidationError(f"chapters[{index}] has invalid core range")
        start_pos = positions[core_start_ref]
        end_pos = positions[core_end_ref]
        if end_pos < start_pos:
            pre_repairs.append(
                {
                    "type": "normalize_reversed_core_chapter_range",
                    "location": f"chapters[{index}]",
                    "old_end_ref": core_end_ref,
                    "new_end_ref": core_start_ref,
                }
            )
            core_end_ref = core_start_ref
            end_pos = start_pos
        refs = chapter.get("refs")
        refs = refs if isinstance(refs, list) else []
        refs = list(dict.fromkeys(
            str(ref)
            for ref in refs
            if str(ref) in positions and start_pos <= positions[str(ref)] <= end_pos
        ))
        if not refs:
            refs = list(dict.fromkeys((core_start_ref, core_end_ref)))
        prepared_chapters.append(
            {
                **chapter,
                "start_ref": core_start_ref,
                "end_ref": core_end_ref,
                "refs": refs,
            }
        )
    prepared = {**raw, "chapters": prepared_chapters}
    summary, quality = validate_summary_object(prepared, segments)
    quality["repairs"].extend(pre_repairs)
    core_chapters = [
        {
            **chapter,
            "core_start_ref": chapter["start_ref"],
            "core_end_ref": chapter["end_ref"],
        }
        for chapter in summary["chapters"]
    ]
    expanded, repairs = _expand_core_chapter_ranges(
        core_chapters,
        segments,
        coverage_end_ref=segments[-1]["segment_id"],
    )
    summary["chapters"] = expanded
    quality["repairs"].extend(repairs)
    quality["checks"].update(
        {
            "core_chapters_identified": True,
            "continuous_ranges_assigned_by_harness": True,
        }
    )
    return summary, quality
def _validate_overview(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    segment_by_id: dict[str, dict[str, Any]],
    overview_refs: list[str],
) -> tuple[str | None, dict[str, Any]]:
    if finish_reason != "stop" or context_truncated:
        raise SummaryValidationError("full summary request did not finish cleanly")
    raw = parse_content(content)
    title = clean_text(raw.get("title"))
    overview = raw.get("overview")
    if not isinstance(overview, dict):
        raise SummaryValidationError("overview must be an object")
    text = clean_text(overview.get("text"))
    if text is None:
        raise SummaryValidationError("overview text is required")
    if len(text) < MIN_OVERVIEW_CHARS:
        raise SummaryValidationError(f"overview text is too short ({len(text)} chars)")
    refs = list(dict.fromkeys(
        str(ref)
        for ref in overview_refs
        if str(ref) in segment_by_id and segment_by_id[str(ref)].get("text")
    ))
    if not refs:
        raise SummaryValidationError("validated chapters contain no overview refs")
    return title, {"text": text, "refs": refs}
def _empty_long_summary() -> dict[str, Any]:
    return {
        "title": None,
        "overview": None,
        "chapters": [],
        "speakers": [],
        "key_points": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "risks": [],
        "keywords": [],
    }
def _validate_actions(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"action review finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("action review input was truncated")
    raw = parse_content(content)
    ref_map, compact_ref_map = _build_compact_ref_map(segments)
    speaker_map, compact_speaker_map = _build_compact_speaker_map(
        [segment["speaker_id"] for segment in segments]
    )
    raw = _expand_payload(raw, compact_ref_map, compact_speaker_map)
    summary, _ = validate_summary_object(
        {**_empty_long_summary(), "action_items": raw.get("action_items", [])},
        segments,
    )
    return summary["action_items"]
def _validate_block_summary(
    content: str,
    finish_reason: Any,
    context_truncated: bool,
    block_segments: list[dict[str, Any]],
    *,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
    profile: DomainProfile = GENERIC_PROFILE,
) -> dict[str, Any]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"block summary finish_reason is {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("block summary input was truncated")
    raw = parse_content(content)
    compact_ref_map = {compact: canonical for canonical, compact in ref_map.items()}
    compact_speaker_map = {compact: canonical for canonical, compact in speaker_map.items()}
    raw = _expand_payload(raw, compact_ref_map, compact_speaker_map)
    title = clean_text(raw.get("title"))
    summary = clean_text(raw.get("summary"))
    if title is None or summary is None:
        raise SummaryValidationError("block summary requires title and summary")
    if len(summary) < profile.summary_min_chars:
        raise SummaryValidationError(
            f"block summary is too short ({len(summary)} chars)"
        )
    by_id = {segment["segment_id"]: segment for segment in block_segments}
    key_refs = raw.get("key_refs")
    key_refs = key_refs if isinstance(key_refs, list) else []
    valid_refs = list(dict.fromkeys(
        str(ref)
        for ref in key_refs
        if str(ref) in by_id and by_id[str(ref)].get("text")
    ))
    if not valid_refs:
        valid_refs = list(dict.fromkeys(
            [block_segments[0]["segment_id"], block_segments[-1]["segment_id"]]
        ))
    continues_raw = raw.get("continues_previous")
    continues_previous = continues_raw is True or (
        isinstance(continues_raw, str)
        and continues_raw.strip().lower() in {"true", "yes", "是"}
    )
    actions: list[dict[str, Any]] = []
    raw_actions = raw.get("action_candidates", [])
    if isinstance(raw_actions, list):
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            task = clean_text(item.get("task"))
            refs = item.get("refs")
            if task is None or not isinstance(refs, list):
                continue
            action_refs = list(dict.fromkeys(
                str(ref)
                for ref in refs
                if str(ref) in by_id and by_id[str(ref)].get("text")
            ))
            if not action_refs:
                continue
            actions.append(
                {
                    "task": task,
                    "owner": clean_text(item.get("owner")),
                    "deadline": clean_text(item.get("deadline")),
                    "refs": action_refs,
                }
            )
    key_points = _clean_bullet_list(raw.get("key_points"), profile.key_points_max)
    anchors = _clean_bullet_list(raw.get("anchors"), profile.anchors_max)
    return {
        "title": title,
        "key_points": key_points,
        "anchors": anchors,
        "summary": summary,
        "continues_previous": continues_previous,
        "refs": valid_refs,
        "action_candidates": actions,
        "start_ref": block_segments[0]["segment_id"],
        "end_ref": block_segments[-1]["segment_id"],
    }
def _clean_bullet_list(raw: Any, cap: int) -> list[str]:
    """把模型给的要点/锚点数组归一成去重、非空、封顶的字符串列表（防泛滥）。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        text = clean_text(item) if not isinstance(item, str) else clean_text(item)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= cap:
            break
    return cleaned
def _summaries_too_similar(left: str, right: str, threshold: float = 0.8) -> bool:
    """字符 bigram Jaccard 判两段摘要是否近乎重复，避免合并时冗余拼接。"""
    def grams(text: str) -> set[str]:
        joined = "".join(str(text).split())
        return {joined[i : i + 2] for i in range(len(joined) - 1)}

    left_grams, right_grams = grams(left), grams(right)
    if not left_grams or not right_grams:
        return False
    return len(left_grams & right_grams) / len(left_grams | right_grams) >= threshold
def _reduce_blocks_to_chapters(
    block_results: list[dict[str, Any]],
    segment_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把逐块摘要合并成最终章节：相邻块 continues_previous 的并入上一章。"""
    chapters: list[dict[str, Any]] = []
    action_candidates: list[dict[str, Any]] = []
    for block in block_results:
        action_candidates.extend(block.get("action_candidates", []))
        if chapters and block.get("continues_previous"):
            chapter = chapters[-1]
            # 近乎重复的续块摘要不再拼接（治 blk-7/blk-8 那种冗余“；”缝）
            if not _summaries_too_similar(chapter["overview"], block["summary"]):
                chapter["overview"] = f"{chapter['overview']}；{block['summary']}"
            chapter["key_points"] = list(dict.fromkeys(chapter.get("key_points", []) + block.get("key_points", [])))
            chapter["anchors"] = list(dict.fromkeys(chapter.get("anchors", []) + block.get("anchors", [])))
            chapter["end_ref"] = block["end_ref"]
            chapter["refs"] = list(dict.fromkeys(chapter["refs"] + block["refs"]))
        else:
            chapters.append(
                {
                    "title": block["title"],
                    "overview": block["summary"],
                    "key_points": list(block.get("key_points", [])),
                    "anchors": list(block.get("anchors", [])),
                    "start_ref": block["start_ref"],
                    "end_ref": block["end_ref"],
                    "refs": list(block["refs"]),
                }
            )
    for chapter in chapters:
        cited = [segment_by_id[ref] for ref in chapter["refs"] if ref in segment_by_id]
        chapter["speaker_ids"] = sorted({item["speaker_id"] for item in cited})
        start_segment = segment_by_id.get(chapter["start_ref"])
        end_segment = segment_by_id.get(chapter["end_ref"])
        chapter["start_ms"] = int(start_segment["start_ms"]) if start_segment else 0
        chapter["end_ms"] = int(end_segment["end_ms"]) if end_segment else 0
    return chapters, action_candidates
