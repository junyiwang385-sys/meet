"""Convert the current board Harness result into the product API result shape."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _integer(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _text(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def normalize_harness_result(
    meeting_id: str,
    language: str,
    harness_result: dict[str, Any],
) -> dict[str, Any]:
    """Return ``MeetingResultV1`` without inventing identities or evidence."""

    # Board Agent wraps the Harness document with task metadata:
    # {"task_id": "...", "result": {"schema_version": "meeting-result.v2", ...}}
    # Keep the adapter tolerant of both the wrapped API response and a raw
    # meeting_result.json document used by local tools.
    source_document = harness_result
    wrapped_result = harness_result.get("result")
    if isinstance(wrapped_result, dict):
        source_document = wrapped_result

    if source_document.get("schema_version") == "meeting-result.v1":
        product_result = copy.deepcopy(source_document)
        product_result["meeting_id"] = meeting_id
        return product_result

    source_status = source_document.get("status")
    transcript_source = _dict(source_document.get("transcript"))
    is_partial_failure = source_status == "failed" and bool(_list(transcript_source.get("segments")))
    if source_status != "ok" and not is_partial_failure:
        raise ValueError("board Harness result is not complete")

    summary = _dict(source_document.get("summary"))
    meeting = _dict(source_document.get("meeting"))
    runtime = _dict(source_document.get("runtime"))

    source_segments = [item for item in _list(transcript_source.get("segments")) if isinstance(item, dict)]
    normalized_segments: list[dict[str, Any]] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(source_segments, 1):
        segment_id = _text(source.get("segment_id"), f"segment-{index}")
        segment = {
            "segment_id": segment_id,
            "start_ms": max(0, _integer(source.get("start_ms"))),
            "end_ms": max(0, _integer(source.get("end_ms"))),
            "speaker_id": _text(source.get("speaker_id"), "unknown"),
            "text": _text(source.get("text")),
            "chapter_id": None,
            "confidence": _number_or_none(source.get("confidence")),
            "review_status": "pending",
            "user_edited": False,
        }
        normalized_segments.append(segment)
        source_by_id[segment_id] = segment

    chapter_items: list[dict[str, Any]] = []
    chapter_ranges: list[tuple[str, int, int]] = []
    for index, source in enumerate(_list(summary.get("chapters")), 1):
        if not isinstance(source, dict):
            continue
        chapter_id = f"chapter-{index}"
        start_ms = max(0, _integer(source.get("start_ms")))
        end_ms = max(start_ms, _integer(source.get("end_ms"), start_ms))
        evidence_ids = [
            f"evidence-{ref}"
            for ref in dict.fromkeys(str(value) for value in _list(source.get("refs")))
            if ref in source_by_id
        ]
        chapter_items.append(
            {
                "chapter_id": chapter_id,
                "index": index,
                "title": _text(source.get("title"), f"章节 {index}"),
                "summary": _text(source.get("overview")),
                "start_ms": start_ms,
                "end_ms": end_ms,
                "evidence_ids": evidence_ids,
                "review_status": "pending",
                "user_edited": False,
            }
        )
        chapter_ranges.append((chapter_id, start_ms, end_ms))

    for segment in normalized_segments:
        for chapter_id, start_ms, end_ms in chapter_ranges:
            if segment["start_ms"] < end_ms and segment["end_ms"] > start_ms:
                segment["chapter_id"] = chapter_id
                break

    evidence_refs: list[str] = []
    overview = summary.get("overview")
    if isinstance(overview, dict):
        evidence_refs.extend(str(value) for value in _list(overview.get("refs")))
    for field in ("chapters", "speakers", "key_points", "decisions", "action_items", "open_questions", "risks"):
        for item in _list(summary.get(field)):
            if isinstance(item, dict):
                evidence_refs.extend(str(value) for value in _list(item.get("refs")))
    evidence = [
        {
            "evidence_id": f"evidence-{segment_id}",
            "segment_id": segment_id,
            "start_ms": source_by_id[segment_id]["start_ms"],
            "end_ms": source_by_id[segment_id]["end_ms"],
            "speaker_id": source_by_id[segment_id]["speaker_id"],
            "quote": source_by_id[segment_id]["text"],
        }
        for segment_id in dict.fromkeys(evidence_refs)
        if segment_id in source_by_id
    ]

    speaker_stats: dict[str, dict[str, Any]] = {}
    for segment in normalized_segments:
        speaker_id = segment["speaker_id"]
        stats = speaker_stats.setdefault(
            speaker_id,
            {
                "speaker_id": speaker_id,
                "display_name": speaker_id,
                "segment_count": 0,
                "duration_ms": 0,
                "user_renamed": False,
            },
        )
        stats["segment_count"] += 1
        stats["duration_ms"] += max(0, segment["end_ms"] - segment["start_ms"])

    # 发言人总结：把 summary.speakers[].overview 并入对应 speaker（板端按 speaker_id 对齐）
    summary_speaker_overview = {
        _text(item.get("speaker_id")): _text(item.get("overview"))
        for item in _list(summary.get("speakers"))
        if isinstance(item, dict) and item.get("speaker_id")
    }
    for speaker_id, stats in speaker_stats.items():
        overview = summary_speaker_overview.get(speaker_id)
        if overview:
            stats["summary"] = overview

    decisions = []
    for index, source in enumerate(_list(summary.get("decisions")), 1):
        if not isinstance(source, dict):
            continue
        decisions.append(
            {
                "decision_id": f"decision-{index}",
                "text": _text(source.get("text")),
                "evidence_ids": [
                    f"evidence-{ref}"
                    for ref in dict.fromkeys(str(value) for value in _list(source.get("refs")))
                    if ref in source_by_id
                ],
                "review_status": "pending",
                "user_edited": False,
            }
        )

    if not decisions:
        # summary 未产决策（多块 map-reduce 路径的已知缺口）时，用 enrichment 抽取的决策兜底。
        # 仅文字：enrichment 决策的 turn_ids 是行号而非 segment_id，暂无法接证据跳转。
        for index, source in enumerate(_list(_dict(source_document.get("enrichment")).get("decisions")), 1):
            if not isinstance(source, dict):
                continue
            text = _text(source.get("decision"))
            if not text:
                continue
            decisions.append(
                {
                    "decision_id": f"decision-e{index}",
                    "text": text,
                    "evidence_ids": [],
                    "review_status": "pending",
                    "user_edited": False,
                }
            )
            if len(decisions) >= 20:
                break

    action_items = []
    for index, source in enumerate(_list(summary.get("action_items")), 1):
        if not isinstance(source, dict):
            continue
        owner = source.get("owner") if isinstance(source.get("owner"), str) else None
        due_date = source.get("deadline") if isinstance(source.get("deadline"), str) else None
        action_items.append(
            {
                "action_id": f"action-{index}",
                "text": _text(source.get("task")),
                "owner": owner,
                "due_date": due_date,
                "evidence_ids": [
                    f"evidence-{ref}"
                    for ref in dict.fromkeys(str(value) for value in _list(source.get("refs")))
                    if ref in source_by_id
                ],
                "review_status": "pending",
                "user_edited": False,
            }
        )

    overview_text = _text(overview.get("text")) if isinstance(overview, dict) else ""
    outline = [
        {
            "node_id": chapter["chapter_id"],
            "level": 1,
            "title": chapter["title"],
            "text": chapter["summary"],
            "evidence_ids": list(chapter["evidence_ids"]),
            "review_status": "pending",
            "user_edited": False,
        }
        for chapter in chapter_items
    ]

    # 内容丰富（对标飞书/阿里）：把板端 enrichment 投影成前端 Enrichment 契约。
    src_enrichment = _dict(source_document.get("enrichment"))
    enrichment: dict[str, Any] | None = None
    if src_enrichment:
        enrichment = {
            "keywords": [str(value) for value in _list(src_enrichment.get("keywords")) if str(value).strip()],
            "quotes": [
                {
                    "quote": _text(item.get("quote")),
                    "comment": _text(item.get("comment")),
                    "segment_id": item.get("ref") if isinstance(item.get("ref"), str) else None,
                    "speaker_id": (
                        source_by_id.get(item["ref"], {}).get("speaker_id")
                        if isinstance(item.get("ref"), str) else None
                    ),
                }
                for item in _list(src_enrichment.get("quotes"))
                if isinstance(item, dict) and _text(item.get("quote"))
            ],
            "qa": [
                {"question": _text(item.get("question")), "answer": _text(item.get("answer"))}
                for item in _list(src_enrichment.get("qa"))
                if isinstance(item, dict) and _text(item.get("question")) and _text(item.get("answer"))
            ],
        }

    duration_ms = _integer(meeting.get("duration_ms"))
    if duration_ms <= 0 and normalized_segments:
        duration_ms = max(segment["end_ms"] for segment in normalized_segments)
    generated_at = runtime.get("finished_at") if isinstance(runtime.get("finished_at"), str) else _now()
    summary_available = bool(summary) and not is_partial_failure
    availability = {
        "transcript": True,
        "speakers": True,
        "minutes": summary_available,
        "chapters": summary_available,
        "decisions": summary_available,
        "action_items": summary_available,
        "evidence": bool(evidence) and not is_partial_failure,
        "formal_version": False,
    }

    return {
        "schema_version": "meeting-result.v1",
        "meeting_id": meeting_id,
        "result_revision": 1,
        "language": language,
        "duration_ms": max(0, duration_ms),
        "generated_at": generated_at,
        "availability": availability,
        "transcript": {
            "complete": not is_partial_failure,
            "segment_count": len(normalized_segments),
            "segments": normalized_segments,
        },
        "speakers": list(speaker_stats.values()),
        "minutes": {"overview": overview_text, "outline": outline} if summary_available else None,
        "chapters": chapter_items if summary_available else None,
        "decisions": decisions if summary_available else None,
        "action_items": action_items if summary_available else None,
        "enrichment": enrichment if summary_available else None,
        "evidence": evidence,
        # Technical details stay in board_result.json/diagnostics.json and are
        # projected only through an explicit ``include=diagnostics`` request.
        "diagnostics": None,
    }


def build_draft_content(
    result: dict[str, Any],
    title: str,
    *,
    finalized: bool = False,
) -> dict[str, Any]:
    """Create the editable draft projection without changing the result cache."""

    def status(value: Any) -> str:
        if finalized:
            return "reviewed"
        return value if value in {"pending", "reviewed", "edited"} else "pending"

    review_marks: dict[str, str] = {}
    for decision in _list(result.get("decisions")):
        if isinstance(decision, dict) and isinstance(decision.get("decision_id"), str):
            review_marks[decision["decision_id"]] = status(decision.get("review_status"))
    for action in _list(result.get("action_items")):
        if isinstance(action, dict) and isinstance(action.get("action_id"), str):
            review_marks[action["action_id"]] = status(action.get("review_status"))
    minutes = result.get("minutes")
    if isinstance(minutes, dict):
        for node in _list(minutes.get("outline")):
            if isinstance(node, dict) and isinstance(node.get("node_id"), str):
                review_marks[node["node_id"]] = status(node.get("review_status"))

    speakers = [item for item in _list(result.get("speakers")) if isinstance(item, dict)]
    speaker_names = {
        item["speaker_id"]: _text(item.get("display_name"), item["speaker_id"])
        for item in speakers
        if isinstance(item.get("speaker_id"), str)
    }

    def clone_items(key: str) -> list[dict[str, Any]]:
        values = []
        for item in _list(result.get(key)):
            if not isinstance(item, dict):
                continue
            cloned = copy.deepcopy(item)
            if "review_status" in cloned:
                cloned["review_status"] = status(cloned.get("review_status"))
            values.append(cloned)
        return values

    minutes_content = None
    if isinstance(minutes, dict):
        minutes_content = copy.deepcopy(minutes)
        minutes_content["outline"] = []
        for node in _list(minutes.get("outline")):
            if not isinstance(node, dict):
                continue
            cloned = copy.deepcopy(node)
            cloned["review_status"] = status(cloned.get("review_status"))
            minutes_content["outline"].append(cloned)

    if finalized:
        for key in list(review_marks):
            review_marks[key] = "reviewed"

    return {
        "title": title,
        "speaker_names": speaker_names,
        "transcript_edits": [],
        "minutes": minutes_content,
        "chapters": clone_items("chapters"),
        "decisions": clone_items("decisions"),
        "action_items": clone_items("action_items"),
        "review_marks": review_marks,
    }


def draft_review_summary(content: dict[str, Any]) -> dict[str, Any]:
    """Count draft review marks using the product's pending/reviewed model."""

    marks = content.get("review_marks")
    statuses = list(marks.values()) if isinstance(marks, dict) else []
    return {
        "pending_count": sum(value == "pending" for value in statuses),
        "reviewed_count": sum(value != "pending" for value in statuses),
    }
