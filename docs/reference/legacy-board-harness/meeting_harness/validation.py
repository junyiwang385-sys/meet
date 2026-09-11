"""Deterministic validation for evidence-linked meeting summaries."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


ARRAY_FIELDS = (
    "chapters",
    "speakers",
    "key_points",
    "decisions",
    "action_items",
    "open_questions",
    "risks",
    "keywords",
)
PLACEHOLDER_VALUES = {
    "无",
    "暂无",
    "没有",
    "未明确",
    "不明确",
    "待确认",
    "n/a",
    "none",
    "null",
    "仍需确认的问题",
    "风险、限制或依赖项",
}
WHITESPACE_RE = re.compile(r"\s+")


class SummaryValidationError(ValueError):
    pass


def empty_summary() -> dict[str, Any]:
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


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SummaryValidationError(f"expected string or null, got {type(value).__name__}")
    text = WHITESPACE_RE.sub(" ", value).strip()
    if not text or text.lower() in PLACEHOLDER_VALUES:
        return None
    return text


def _escape_control_chars_inside_json_strings(content: str) -> str:
    """Escape literal controls only while scanning a JSON string value."""
    output: list[str] = []
    in_string = False
    escaped = False
    for char in content:
        code = ord(char)
        if in_string:
            if escaped:
                output.append(char)
                escaped = False
                continue
            if char == "\\":
                output.append(char)
                escaped = True
                continue
            if char == '"':
                output.append(char)
                in_string = False
                continue
            if code < 0x20:
                replacements = {"\\n": "n", "\\r": "r", "\\t": "t", "\\b": "b", "\\f": "f"}
                output.append("\\" + replacements.get(char, f"u{code:04x}"))
                continue
        elif char == '"':
            in_string = True
        output.append(char)
    return "".join(output)


def parse_content(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        if "Invalid control character" not in str(exc):
            raise SummaryValidationError(f"LLM content is not valid JSON: {exc}") from exc
        repaired = _escape_control_chars_inside_json_strings(content)
        try:
            value = json.loads(repaired)
        except json.JSONDecodeError:
            raise SummaryValidationError(f"LLM content is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SummaryValidationError("LLM content must be a JSON object")
    return value


def normalize_refs(
    refs: Any,
    segment_by_id: dict[str, dict[str, Any]],
    repairs: list[dict[str, Any]],
    location: str,
) -> list[str]:
    if not isinstance(refs, list):
        raise SummaryValidationError(f"{location}.refs must be an array")
    valid = []
    seen = set()
    invalid = []
    for ref in refs:
        ref = str(ref)
        if ref not in segment_by_id:
            invalid.append(ref)
        elif not segment_by_id[ref].get("text"):
            repairs.append({"type": "drop_empty_text_ref", "location": location, "value": ref})
        elif ref not in seen:
            valid.append(ref)
            seen.add(ref)
    if invalid:
        repairs.append({"type": "drop_invalid_refs", "location": location, "values": invalid})
    return valid


def normalize_evidence_item(
    item: Any,
    *,
    text_key: str,
    segment_by_id: dict[str, dict[str, Any]],
    repairs: list[dict[str, Any]],
    location: str,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        raise SummaryValidationError(f"{location} must be an object")
    text = clean_text(item.get(text_key))
    refs = normalize_refs(item.get("refs"), segment_by_id, repairs, location)
    if text is None or not refs:
        repairs.append({"type": "drop_unsupported_item", "location": location})
        return None
    return {text_key: text, "refs": refs}


def normalize_summary(
    raw: dict[str, Any],
    segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    segment_by_id = {item["segment_id"]: item for item in segments}
    speaker_ids = {item["speaker_id"] for item in segments}
    repairs: list[dict[str, Any]] = []
    warnings: list[str] = []
    summary = empty_summary()

    unknown_fields = sorted(set(raw) - set(summary))
    if unknown_fields:
        warnings.append(f"ignored unknown top-level fields: {unknown_fields}")

    summary["title"] = clean_text(raw.get("title"))

    overview_raw = raw.get("overview")
    if overview_raw is not None:
        overview = normalize_evidence_item(
            overview_raw,
            text_key="text",
            segment_by_id=segment_by_id,
            repairs=repairs,
            location="overview",
        )
        summary["overview"] = overview

    for field in ARRAY_FIELDS:
        value = raw.get(field, [])
        if not isinstance(value, list):
            raise SummaryValidationError(f"{field} must be an array")

    for index, item in enumerate(raw.get("chapters", [])):
        location = f"chapters[{index}]"
        if not isinstance(item, dict):
            raise SummaryValidationError(f"{location} must be an object")
        title = clean_text(item.get("title"))
        overview = clean_text(item.get("overview"))
        refs = normalize_refs(item.get("refs"), segment_by_id, repairs, location)
        if title is None or overview is None or not refs:
            repairs.append({"type": "drop_unsupported_item", "location": location})
            continue
        start_ref = str(item.get("start_ref") or refs[0])
        end_ref = str(item.get("end_ref") or refs[-1])
        if start_ref not in segment_by_id or end_ref not in segment_by_id:
            repairs.append({"type": "drop_invalid_chapter_range", "location": location})
            continue
        start_segment = segment_by_id[start_ref]
        end_segment = segment_by_id[end_ref]
        if start_segment["start_ms"] > end_segment["start_ms"]:
            repairs.append({"type": "drop_invalid_chapter_range", "location": location})
            continue
        cited = [segment_by_id[ref] for ref in refs]
        summary["chapters"].append(
            {
                "title": title,
                "overview": overview,
                "speaker_ids": sorted({segment["speaker_id"] for segment in cited}),
                "start_ms": start_segment["start_ms"],
                "end_ms": end_segment["end_ms"],
                "start_ref": start_ref,
                "end_ref": end_ref,
                "refs": refs,
            }
        )

    for index, item in enumerate(raw.get("speakers", [])):
        location = f"speakers[{index}]"
        if not isinstance(item, dict):
            raise SummaryValidationError(f"{location} must be an object")
        speaker_id = str(item.get("speaker_id") or "")
        overview = clean_text(item.get("overview"))
        refs = normalize_refs(item.get("refs"), segment_by_id, repairs, location)
        own_refs = [ref for ref in refs if segment_by_id[ref]["speaker_id"] == speaker_id]
        if own_refs != refs:
            repairs.append({"type": "drop_cross_speaker_refs", "location": location})
        if speaker_id not in speaker_ids or overview is None or not own_refs:
            repairs.append({"type": "drop_unsupported_item", "location": location})
            continue
        summary["speakers"].append({"speaker_id": speaker_id, "overview": overview, "refs": own_refs})

    for field in ("key_points", "decisions", "open_questions", "risks"):
        for index, item in enumerate(raw.get(field, [])):
            normalized = normalize_evidence_item(
                item,
                text_key="text",
                segment_by_id=segment_by_id,
                repairs=repairs,
                location=f"{field}[{index}]",
            )
            if normalized:
                summary[field].append(normalized)

    for index, item in enumerate(raw.get("keywords", [])):
        normalized = normalize_evidence_item(
            item,
            text_key="keyword",
            segment_by_id=segment_by_id,
            repairs=repairs,
            location=f"keywords[{index}]",
        )
        if normalized:
            summary["keywords"].append(normalized)

    for index, item in enumerate(raw.get("action_items", [])):
        location = f"action_items[{index}]"
        if not isinstance(item, dict):
            raise SummaryValidationError(f"{location} must be an object")
        task = clean_text(item.get("task"))
        refs = normalize_refs(item.get("refs"), segment_by_id, repairs, location)
        if task is None or not refs:
            repairs.append({"type": "drop_unsupported_item", "location": location})
            continue
        cited_text = " ".join(segment_by_id[ref]["text"] for ref in refs)
        owner = clean_text(item.get("owner"))
        if owner is not None:
            owner_supported = owner in speaker_ids and any(
                segment_by_id[ref]["speaker_id"] == owner for ref in refs
            )
            if not owner_supported:
                repairs.append({"type": "clear_unsupported_owner", "location": location, "value": owner})
                owner = None
        deadline = clean_text(item.get("deadline"))
        if deadline is not None and deadline not in cited_text:
            repairs.append({"type": "clear_unsupported_deadline", "location": location, "value": deadline})
            deadline = None
        summary["action_items"].append(
            {"task": task, "owner": owner, "deadline": deadline, "refs": refs}
        )

    for field in ARRAY_FIELDS:
        seen = set()
        unique = []
        for item in summary[field]:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key in seen:
                repairs.append({"type": "drop_duplicate", "location": field})
                continue
            seen.add(key)
            unique.append(item)
        summary[field] = unique

    quality = {
        "status": "pass",
        "checks": {
            "json_parse": True,
            "schema": True,
            "refs": True,
            "times": True,
            "speakers": True,
            "no_placeholder_text": True,
        },
        "counts": {
            "repairs": len(repairs),
            "invalid_refs": sum(len(item.get("values", [])) for item in repairs if item["type"] == "drop_invalid_refs"),
            "dropped_items": sum(item["type"] == "drop_unsupported_item" for item in repairs),
        },
        "repairs": repairs,
        "warnings": warnings,
    }
    return summary, quality


def validate_summary_object(
    raw: dict[str, Any],
    segments: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw, dict):
        raise SummaryValidationError("summary must be a JSON object")
    return normalize_summary(deepcopy(raw), segments)


def validate_llm_result(
    content: str,
    finish_reason: Any,
    segments: list[dict[str, Any]],
    *,
    context_truncated: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if finish_reason != "stop":
        raise SummaryValidationError(f"finish_reason must be 'stop', got {finish_reason!r}")
    if context_truncated:
        raise SummaryValidationError("rkllm3-server reported input truncation")
    raw = parse_content(content)
    summary, quality = validate_summary_object(raw, segments)
    quality["checks"].update({"finish_reason": True, "context_not_truncated": True})
    return summary, quality
