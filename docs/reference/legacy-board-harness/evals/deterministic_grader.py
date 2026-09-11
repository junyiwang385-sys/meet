"""Deterministic grading for evidence-linked meeting summaries."""

from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from typing import Any

try:
    from meeting_harness.validation import SummaryValidationError, validate_summary_object
except Exception:  # pragma: no cover - allows data-only smoke tests
    SummaryValidationError = ValueError
    validate_summary_object = None

_NORMALIZE_RE = re.compile(r"[^\w一-鿿]+", re.UNICODE)


def _norm(text: Any) -> str:
    return _NORMALIZE_RE.sub("", str(text or "")).lower()


def _similarity(left: Any, right: Any) -> float:
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if len(a) >= 4 and len(b) >= 4:
        overlap = len(set(a) & set(b)) / max(1, len(set(a) | set(b)))
        return max(ratio, overlap)
    return ratio


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _match_texts(expected: list[dict[str, Any]], actual: list[dict[str, Any]], threshold: float = 0.30) -> dict[str, Any]:
    candidates = []
    for expected_item in expected:
        best = None
        for index, actual_item in enumerate(actual):
            score = _similarity(expected_item.get("text"), actual_item.get("text"))
            if best is None or score > best["score"]:
                best = {"index": index, "score": score}
        if best and best["score"] >= threshold:
            candidates.append((best["score"], expected_item, best["index"]))
    used_expected: set[str] = set()
    used_actual: set[int] = set()
    matches = []
    for score, expected_item, actual_index in sorted(candidates, reverse=True, key=lambda item: item[0]):
        expected_id = str(expected_item["id"])
        if expected_id in used_expected or actual_index in used_actual:
            continue
        used_expected.add(expected_id)
        used_actual.add(actual_index)
        matches.append({"expected_id": expected_id, "actual_index": actual_index, "score": round(score, 4)})
    missing = [str(item["id"]) for item in expected if str(item["id"]) not in used_expected]
    extra = [index for index in range(len(actual)) if index not in used_actual]
    precision = len(matches) / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = len(matches) / len(expected) if expected else 1.0
    return {
        "expected_count": len(expected),
        "actual_count": len(actual),
        "matched": matches,
        "missing_ids": missing,
        "extra_indices": extra,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(_f1(precision, recall), 4),
    }


def normalize_expected(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert expected JSON into explicit coverage constraints."""
    facts: list[dict[str, Any]] = []
    core_facts = raw.get("core_facts")
    has_core_facts = isinstance(core_facts, list) and bool(core_facts)
    if has_core_facts:
        for index, item in enumerate(core_facts, 1):
            if not isinstance(item, dict) or not item.get("text"):
                continue
            facts.append({
                "id": f"core-fact-{index:03d}",
                "text": item["text"],
                "refs": item.get("refs", []),
                "importance": item.get("importance", "major"),
            })
    else:
        overview = raw.get("overview")
        if isinstance(overview, dict) and overview.get("text"):
            facts.append({"id": "fact-overview", "text": overview["text"], "refs": overview.get("refs", []), "importance": "critical"})
        for index, chapter in enumerate(raw.get("chapters", [])):
            if isinstance(chapter, dict) and chapter.get("overview"):
                facts.append({
                    "id": f"fact-chapter-{index + 1:03d}",
                    "text": chapter["overview"],
                    "refs": chapter.get("refs", []),
                    "title": chapter.get("title"),
                    "start_ref": chapter.get("start_ref"),
                    "end_ref": chapter.get("end_ref"),
                    "importance": "major",
                })
    # Action items remain separate diagnostics. Legacy expected files include
    # them in the old completeness denominator; explicit core_facts do not.
    action_items = []
    for index, item in enumerate(raw.get("action_items", [])):
        if isinstance(item, dict) and item.get("task"):
            action_items.append({
                "id": f"action-{index + 1:03d}",
                "text": item["task"],
                "owner": item.get("owner"),
                "deadline": item.get("deadline"),
                "refs": item.get("refs", []),
                "importance": "critical",
            })
    coverage_facts = facts + ([] if has_core_facts else action_items)
    coverage_metric = {
        "name": "core_content_coverage" if has_core_facts else "legacy_weighted_completeness",
        "version": "core_content_coverage_v1" if has_core_facts else "legacy_weighted_completeness_v1",
        "basis": "explicit_core_facts" if has_core_facts else "overview_chapters_actions",
    }
    return {
        "title": raw.get("title"),
        "key_facts": facts,
        "coverage_facts": coverage_facts,
        "coverage_metric": coverage_metric,
        "chapters": [item for item in raw.get("chapters", []) if isinstance(item, dict)],
        "speakers": [item for item in raw.get("speakers", []) if isinstance(item, dict)],
        "action_items": action_items,
        "critical_errors": raw.get("critical_errors", []),
        "source": raw.get("source"),
    }


def _candidate_texts(summary: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    if isinstance(summary.get("overview"), dict) and summary["overview"].get("text"):
        items.append({"id": "candidate-overview", "text": summary["overview"]["text"]})
    for field in ("chapters", "speakers"):
        for index, item in enumerate(summary.get(field, [])):
            if not isinstance(item, dict):
                continue
            text = item.get("overview") or item.get("text")
            if text:
                items.append({"id": f"candidate-{field}-{index + 1:03d}", "text": text})
    for index, item in enumerate(summary.get("action_items", [])):
        if isinstance(item, dict) and item.get("task"):
            items.append({
                "id": f"candidate-action_items-{index + 1:03d}",
                "text": item["task"],
            })
    return items


def _parse_and_validate(candidate: dict[str, Any], segments: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    if not isinstance(candidate, dict):
        return {}, {"status": "fail", "checks": {"json_parse": False, "schema": False}}, "candidate summary must be an object"
    if validate_summary_object is None:
        return candidate, {"status": "skipped", "checks": {"json_parse": True, "schema": True}}, None
    try:
        normalized, quality = validate_summary_object(candidate, segments)
        return normalized, quality, None
    except (SummaryValidationError, KeyError, TypeError, ValueError) as exc:
        return {}, {"status": "fail", "checks": {"json_parse": True, "schema": False}, "error": str(exc)}, str(exc)


def grade_summary(candidate: dict[str, Any] | None, segments: list[dict[str, Any]], expected_raw: dict[str, Any], *, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = normalize_expected(expected_raw)
    if candidate is None:
        summary, validation = {}, {"status": "fail", "checks": {"json_parse": False, "schema": False, "refs": False}}
        validation_error = "candidate summary was not generated"
    else:
        summary, validation, validation_error = _parse_and_validate(candidate, segments)
    segment_ids = [segment["segment_id"] for segment in segments if segment.get("text")]
    by_id = {segment["segment_id"]: segment for segment in segments}
    all_refs = []
    for field in ("overview", "chapters", "speakers", "key_points", "decisions", "action_items", "open_questions", "risks", "keywords"):
        value = summary.get(field)
        values = [value] if isinstance(value, dict) else value if isinstance(value, list) else []
        for item in values:
            if isinstance(item, dict):
                all_refs.extend(ref for ref in item.get("refs", []) if ref in by_id)
    chapters = summary.get("chapters", []) if isinstance(summary.get("chapters"), list) else []
    chapter_ranges = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        start_ref = chapter.get("start_ref")
        end_ref = chapter.get("end_ref")
        if start_ref in by_id and end_ref in by_id:
            chapter_ranges.append((segment_ids.index(start_ref) if start_ref in segment_ids else -1, segment_ids.index(end_ref) if end_ref in segment_ids else -1))
    chapter_ranges.sort()
    continuity = bool(chapter_ranges) and chapter_ranges[0][0] == 0 and chapter_ranges[-1][1] == len(segment_ids) - 1 and all(left == right + 1 for (_, right), (left, _) in zip(chapter_ranges, chapter_ranges[1:]))
    covered_ids = set()
    for start, end in chapter_ranges:
        if start >= 0 and end >= start:
            covered_ids.update(segment_ids[start : end + 1])
    chapter_coverage = len(covered_ids) / len(segment_ids) if segment_ids else 1.0
    speaker_items = summary.get("speakers", []) if isinstance(summary.get("speakers"), list) else []
    speaker_ref_valid = all(
        isinstance(item, dict)
        and item.get("speaker_id") in {segment.get("speaker_id") for segment in segments}
        and all(by_id.get(ref, {}).get("speaker_id") == item.get("speaker_id") for ref in item.get("refs", []))
        for item in speaker_items
    )
    repairs = validation.get("repairs", []) if isinstance(validation, dict) else []
    repair_types = Counter(item.get("type") for item in repairs if isinstance(item, dict))
    candidate_facts = _candidate_texts(summary)
    fact_match = _match_texts(expected["key_facts"], candidate_facts)
    expected_actions = expected["action_items"]
    candidate_actions = [item for item in summary.get("action_items", []) if isinstance(item, dict)]
    actual_actions = [{"id": f"candidate-action-{index + 1:03d}", "text": item.get("task", ""), "owner": item.get("owner"), "deadline": item.get("deadline"), "refs": item.get("refs", [])} for index, item in enumerate(candidate_actions)]
    action_match = _match_texts(expected_actions, actual_actions)
    owner_correct = deadline_correct = 0
    for match in action_match["matched"]:
        expected_item = expected_actions[next(index for index, item in enumerate(expected_actions) if str(item["id"]) == match["expected_id"])]
        actual_item = actual_actions[match["actual_index"]]
        if expected_item.get("owner") is None or expected_item.get("owner") == actual_item.get("owner"):
            owner_correct += 1
        if expected_item.get("deadline") is None or expected_item.get("deadline") == actual_item.get("deadline"):
            deadline_correct += 1
    matched_count = len(action_match["matched"])
    action_match["owner_accuracy"] = round(owner_correct / matched_count, 4) if matched_count else (1.0 if not expected_actions else 0.0)
    action_match["deadline_accuracy"] = round(deadline_correct / matched_count, 4) if matched_count else (1.0 if not expected_actions else 0.0)
    grade = {
        "status": "pass" if validation_error is None else "fail",
        "validation": validation,
        "validation_error": validation_error,
        "checks": {
            "json_parse": validation.get("checks", {}).get("json_parse", False),
            "schema": validation.get("checks", {}).get("schema", False),
            "refs": validation.get("checks", {}).get("refs", False),
            "chapter_continuity": continuity,
            "full_timeline_coverage": chapter_coverage >= 0.999,
            "speaker_reference_validity": speaker_ref_valid,
            "context_not_truncated": not bool((runtime or {}).get("context_truncated")),
        },
        "coverage": {
            "segment_count": len(segment_ids),
            "referenced_segment_count": len(set(all_refs)),
            "chapter_coverage": round(chapter_coverage, 4),
            "chapter_count": len(chapters),
        },
        "key_facts": fact_match,
        "action_items": {**action_match, "applicable": bool(expected_actions)},
        "unsupported_owner_count": repair_types.get("clear_unsupported_owner", 0),
        "unsupported_deadline_count": repair_types.get("clear_unsupported_deadline", 0),
        "repairs": {"total": len(repairs), "by_type": dict(repair_types)},
        "runtime": runtime or {},
    }
    return grade
