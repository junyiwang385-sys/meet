#!/usr/bin/env python3
"""Generate a chronological meeting overview from Batch ASR turns on RK1828.

This additive runner reuses the stable board/runtime infrastructure from
``meeting_minutes_map_reduce_v0`` while keeping the overview/chapter contract
independent from the existing evidence-backed minutes contract.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import meeting_minutes_map_reduce_v0 as infra


DEFAULT_TURNS = infra.DEFAULT_TURNS
DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/minutes/meeting_overview_map_reduce_v0"
DEFAULT_MODEL_DIR = infra.DEFAULT_MODEL_DIR
DEFAULT_SERVER = infra.DEFAULT_SERVER
DEFAULT_HOST = infra.DEFAULT_HOST
DEFAULT_PORT = infra.DEFAULT_PORT


ValidationError = infra.ValidationError
EnvironmentError = infra.EnvironmentError
PromptBudgetExceeded = infra.PromptBudgetExceeded
MinutesError = infra.MinutesError


MAP_MODEL_KEYS = ("chapters", "warnings")
MAP_CHAPTER_KEYS = ("title", "summary", "key_points", "turn_ids")
MAP_OUTPUT_CHAPTER_KEYS = (
    "title", "summary", "key_points", "turn_ids", "start", "end",
)
REDUCE_MODEL_KEYS = (
    "meeting_title", "overall_topic", "executive_summary", "chapters", "warnings",
)
REDUCE_CHAPTER_KEYS = ("title", "summary", "key_points", "source_ids")
OVERVIEW_KEYS = (
    "schema_version", "meeting_title", "overall_topic", "executive_summary",
    "chapters", "warnings",
)
OVERVIEW_CHAPTER_KEYS = (
    "title", "start", "end", "summary", "key_points", "turn_ids",
)


def normalize_source_id_list(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    result: List[Any] = []
    for item in value:
        normalized = infra.normalize_identifier(item)
        if isinstance(normalized, str):
            match = re.fullmatch(
                r"v0*(\d+)-chapter-?0*(\d+)",
                normalized,
                flags=re.IGNORECASE,
            )
            if match:
                normalized = f"v{int(match.group(1))}-chapter-{int(match.group(2))}"
        result.append(normalized)
    return result


def normalize_overview_model_output(data: Dict[str, Any], phase: str) -> Dict[str, Any]:
    normalized = dict(data)
    if normalized.get("schema_version") is None:
        normalized.pop("schema_version", None)
    if "warnings" in normalized:
        normalized["warnings"] = infra.normalize_warning_list(normalized.get("warnings"))
    chapters = normalized.get("chapters")
    if isinstance(chapters, list):
        normalized_chapters: List[Any] = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                normalized_chapters.append(chapter)
                continue
            normalized_chapter = dict(chapter)
            if phase == "map" and "turn_ids" in normalized_chapter:
                normalized_chapter["turn_ids"] = infra.normalize_int_list(
                    normalized_chapter["turn_ids"]
                )
            if phase == "reduce" and "source_ids" in normalized_chapter:
                normalized_chapter["source_ids"] = normalize_source_id_list(
                    normalized_chapter["source_ids"]
                )
            normalized_chapters.append(normalized_chapter)
        normalized["chapters"] = normalized_chapters
    return normalized


def validate_string(value: Any, path: str, errors: List[str], non_empty: bool = False) -> None:
    if not isinstance(value, str):
        errors.append(f"{path} must be a string")
    elif non_empty and not value.strip():
        errors.append(f"{path} must be a non-empty string")


def ordered_turn_ids(turn_ids: Iterable[int], turns: List[Dict[str, Any]]) -> List[int]:
    order = {turn["id"]: index for index, turn in enumerate(turns)}
    return sorted(set(turn_ids), key=lambda turn_id: order.get(turn_id, len(order)))


def materialize_turn_ids(
    value: Any,
    turns: List[Dict[str, Any]],
    path: str,
    errors: List[str],
) -> Tuple[List[int], float, float]:
    normalized = infra.normalize_int_list(value)
    if not isinstance(normalized, list) or not normalized:
        errors.append(f"{path} must be a non-empty integer array")
        return [], 0.0, 0.0

    lookup = {turn["id"]: turn for turn in turns}
    valid: List[int] = []
    for index, turn_id in enumerate(normalized):
        if not isinstance(turn_id, int) or isinstance(turn_id, bool):
            errors.append(f"{path}[{index}] must be an integer")
            continue
        if turn_id not in lookup:
            errors.append(f"{path}[{index}] references unknown turn {turn_id}")
            continue
        if turn_id not in valid:
            valid.append(turn_id)

    if not valid:
        return [], 0.0, 0.0
    valid = ordered_turn_ids(valid, turns)
    starts = [float(lookup[turn_id]["start"]) for turn_id in valid]
    ends = [float(lookup[turn_id]["end"]) for turn_id in valid]
    return valid, min(starts), max(ends)


def materialize_map_output(
    data: Dict[str, Any],
    expected_window: Dict[str, Any],
    allowed_turns: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    data = normalize_overview_model_output(data, "map")
    errors: List[str] = []
    infra.add_exact_key_errors(data, MAP_MODEL_KEYS, "$", errors)
    output: Dict[str, Any] = {
        "schema_version": "meeting_overview_map_v0",
        "window_id": expected_window["window_id"],
        "time_range": {
            "start": float(expected_window["start"]),
            "end": float(expected_window["end"]),
        },
        "chapters": [],
        "warnings": infra.normalize_warning_list(data.get("warnings")) or [],
    }

    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        errors.append("$.chapters must be an array")
        chapters = []

    allowed_ids = ordered_turn_ids(
        (turn["id"] for turn in allowed_turns), allowed_turns
    )
    single_turn_id = allowed_ids[0] if len(allowed_ids) == 1 else None
    used_turn_ids: Dict[int, int] = {}
    converted: List[Dict[str, Any]] = []
    for index, chapter in enumerate(chapters):
        path = f"$.chapters[{index}]"
        if not isinstance(chapter, dict):
            errors.append(f"{path} must be an object")
            continue
        chapter = dict(chapter)
        if single_turn_id is not None:
            normalized_refs = infra.normalize_int_list(chapter.get("turn_ids"))
            integer_refs = (
                [item for item in normalized_refs if isinstance(item, int) and not isinstance(item, bool)]
                if isinstance(normalized_refs, list)
                else []
            )
            if not integer_refs:
                chapter["turn_ids"] = [single_turn_id]
            elif isinstance(normalized_refs, list):
                chapter["turn_ids"] = normalized_refs
        infra.add_exact_key_errors(chapter, MAP_CHAPTER_KEYS, path, errors)
        validate_string(chapter.get("title"), f"{path}.title", errors, non_empty=True)
        validate_string(chapter.get("summary"), f"{path}.summary", errors)
        infra.validate_string_list(chapter.get("key_points"), f"{path}.key_points", errors)
        turn_ids, start, end = materialize_turn_ids(
            chapter.get("turn_ids"), allowed_turns, f"{path}.turn_ids", errors
        )
        for turn_id in turn_ids:
            if turn_id in used_turn_ids:
                errors.append(
                    f"{path}.turn_ids reuses turn {turn_id} from chapter "
                    f"{used_turn_ids[turn_id]}"
                )
            else:
                used_turn_ids[turn_id] = index
        converted.append({
            "title": chapter.get("title"),
            "summary": chapter.get("summary"),
            "key_points": chapter.get("key_points"),
            "turn_ids": turn_ids,
            "start": start,
            "end": end,
        })

    converted.sort(key=lambda item: (float(item["start"]), float(item["end"])))
    output["chapters"] = converted
    infra.validate_string_list(output["warnings"], "$.warnings", errors)
    return output, errors


def validate_map_model_output(
    data: Any,
    expected_window: Dict[str, Any],
    allowed_turns: List[Dict[str, Any]],
) -> List[str]:
    if not isinstance(data, dict):
        return ["$ must be an object"]
    _, errors = materialize_map_output(data, expected_window, allowed_turns)
    return errors


def validate_map_output(
    data: Any,
    expected_window: Dict[str, Any],
    allowed_turns: List[Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["$ must be an object"]
    expected_keys = ("schema_version", "window_id", "time_range", "chapters", "warnings")
    infra.add_exact_key_errors(data, expected_keys, "$", errors)
    if data.get("schema_version") != "meeting_overview_map_v0":
        errors.append("$.schema_version must be meeting_overview_map_v0")
    if data.get("window_id") != expected_window["window_id"]:
        errors.append(f"$.window_id must be {expected_window['window_id']}")

    time_range = data.get("time_range")
    if not isinstance(time_range, dict):
        errors.append("$.time_range must be an object")
    else:
        infra.add_exact_key_errors(time_range, ("start", "end"), "$.time_range", errors)
        start, end = time_range.get("start"), time_range.get("end")
        if not infra.is_number(start) or not infra.is_number(end):
            errors.append("$.time_range.start/end must be numbers")
        elif (
            abs(float(start) - float(expected_window["start"])) > 1e-6
            or abs(float(end) - float(expected_window["end"])) > 1e-6
        ):
            errors.append("$.time_range must match the input window")

    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        errors.append("$.chapters must be an array")
        chapters = []

    used_turn_ids: Dict[int, int] = {}
    previous_key: Optional[Tuple[float, float]] = None
    for index, chapter in enumerate(chapters):
        path = f"$.chapters[{index}]"
        if not isinstance(chapter, dict):
            errors.append(f"{path} must be an object")
            continue
        infra.add_exact_key_errors(chapter, MAP_OUTPUT_CHAPTER_KEYS, path, errors)
        validate_string(chapter.get("title"), f"{path}.title", errors, non_empty=True)
        validate_string(chapter.get("summary"), f"{path}.summary", errors)
        infra.validate_string_list(chapter.get("key_points"), f"{path}.key_points", errors)
        turn_ids, expected_start, expected_end = materialize_turn_ids(
            chapter.get("turn_ids"), allowed_turns, f"{path}.turn_ids", errors
        )
        if chapter.get("turn_ids") != turn_ids:
            errors.append(f"{path}.turn_ids must be unique and in source order")
        start, end = chapter.get("start"), chapter.get("end")
        if not infra.is_number(start) or not infra.is_number(end):
            errors.append(f"{path}.start/end must be numbers")
        else:
            start_f, end_f = float(start), float(end)
            if abs(start_f - expected_start) > 1e-6 or abs(end_f - expected_end) > 1e-6:
                errors.append(f"{path}.start/end must match referenced turns")
            key = (start_f, end_f)
            if previous_key is not None and key < previous_key:
                errors.append("$.chapters must be in chronological order")
            previous_key = key
        for turn_id in turn_ids:
            if turn_id in used_turn_ids:
                errors.append(
                    f"{path}.turn_ids reuses turn {turn_id} from chapter "
                    f"{used_turn_ids[turn_id]}"
                )
            else:
                used_turn_ids[turn_id] = index

    infra.validate_string_list(data.get("warnings"), "$.warnings", errors)
    return errors


def transform_map_output(
    data: Dict[str, Any],
    expected_window: Dict[str, Any],
    allowed_turns: List[Dict[str, Any]],
) -> Dict[str, Any]:
    output, errors = materialize_map_output(data, expected_window, allowed_turns)
    errors.extend(validate_map_output(output, expected_window, allowed_turns))
    if errors:
        raise ValidationError("; ".join(errors))
    return output


def overview_time_range(value: Dict[str, Any]) -> Tuple[float, float]:
    starts: List[float] = []
    ends: List[float] = []
    for key in ("time_range", "_source_time_range"):
        source_range = value.get(key)
        if not isinstance(source_range, dict):
            continue
        start, end = source_range.get("start"), source_range.get("end")
        if infra.is_number(start) and infra.is_number(end):
            starts.append(float(start))
            ends.append(float(end))
    chapters = value.get("chapters")
    if isinstance(chapters, list):
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            start, end = chapter.get("start"), chapter.get("end")
            if infra.is_number(start) and infra.is_number(end):
                starts.append(float(start))
                ends.append(float(end))
    return (min(starts), max(ends)) if starts else (0.0, 0.0)


def stable_union_warnings(values: Iterable[Dict[str, Any]]) -> List[str]:
    result: List[str] = []
    for value in values:
        warnings = infra.normalize_warning_list(value.get("warnings"))
        if not isinstance(warnings, list):
            continue
        for warning in warnings:
            if warning not in result:
                result.append(warning)
    return result


def normalize_reduce_inputs(values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, value in enumerate(values, 1):
        schema_version = value.get("schema_version")
        if schema_version == "meeting_overview_map_v0":
            start, end = overview_time_range(value)
            normalized.append({
                "schema_version": "meeting_overview_map_v0",
                "window_id": value.get("window_id", index),
                "time_range": value.get("time_range", {"start": start, "end": end}),
                "chapters": value.get("chapters", []),
                "warnings": value.get("warnings", []),
            })
            continue
        if schema_version == "meeting_overview_v0":
            start, end = overview_time_range(value)
            normalized.append({
                "schema_version": "meeting_overview_map_v0",
                "window_id": index,
                "time_range": {"start": start, "end": end},
                "chapters": value.get("chapters", []),
                "warnings": value.get("warnings", []),
            })
            continue
        raise ValidationError(f"unsupported REDUCE input schema at index {index}")

    normalized.sort(key=lambda item: (
        float(item.get("time_range", {}).get("start", 0.0)),
        float(item.get("time_range", {}).get("end", 0.0)),
        int(item.get("window_id", 0)),
    ))
    return normalized


def build_reduce_sources(
    values: List[Dict[str, Any]],
    turns: List[Dict[str, Any]],
) -> Tuple[
    List[Dict[str, Any]],
    Dict[str, Dict[str, Any]],
    List[str],
    List[str],
]:
    normalized = normalize_reduce_inputs(values)
    prompt_values: List[Dict[str, Any]] = []
    source_lookup: Dict[str, Dict[str, Any]] = {}
    ordered_source_ids: List[str] = []
    source_order = 0
    turn_lookup = {turn["id"]: turn for turn in turns}
    claimed_turn_ids: set[int] = set()

    for value_index, value in enumerate(normalized, 1):
        prompt_value: Dict[str, Any] = {
            "schema_version": "meeting_overview_map_v0",
            "window_id": value.get("window_id", value_index),
            "time_range": value.get("time_range", {"start": 0.0, "end": 0.0}),
            "chapters": [],
            "warnings": infra.normalize_warning_list(value.get("warnings")) or [],
        }
        chapters = value.get("chapters")
        emitted_index = 0
        if isinstance(chapters, list):
            sorted_chapters = sorted(
                (item for item in chapters if isinstance(item, dict)),
                key=lambda item: (float(item.get("start", 0.0)), float(item.get("end", 0.0))),
            )
            for chapter in sorted_chapters:
                normalized_turn_ids = infra.normalize_int_list(chapter.get("turn_ids"))
                if not isinstance(normalized_turn_ids, list):
                    continue
                unique_turn_ids: List[int] = []
                for turn_id in normalized_turn_ids:
                    if (
                        isinstance(turn_id, int)
                        and not isinstance(turn_id, bool)
                        and turn_id in turn_lookup
                        and turn_id not in claimed_turn_ids
                    ):
                        unique_turn_ids.append(turn_id)
                        claimed_turn_ids.add(turn_id)
                unique_turn_ids = ordered_turn_ids(unique_turn_ids, turns)
                if not unique_turn_ids:
                    continue

                emitted_index += 1
                source_id = f"v{value_index}-chapter-{emitted_index}"
                starts = [float(turn_lookup[turn_id]["start"]) for turn_id in unique_turn_ids]
                ends = [float(turn_lookup[turn_id]["end"]) for turn_id in unique_turn_ids]
                start, end = min(starts), max(ends)
                source_lookup[source_id] = {
                    "source_order": source_order,
                    "turn_ids": unique_turn_ids,
                    "start": start,
                    "end": end,
                }
                ordered_source_ids.append(source_id)
                source_order += 1
                prompt_value["chapters"].append({
                    "source_id": source_id,
                    "title": chapter.get("title"),
                    "summary": chapter.get("summary"),
                    "key_points": chapter.get("key_points"),
                    "start": start,
                    "end": end,
                })
        prompt_values.append(prompt_value)

    return prompt_values, source_lookup, ordered_source_ids, stable_union_warnings(normalized)


def validate_reduce_contract(
    data: Dict[str, Any],
    source_lookup: Dict[str, Dict[str, Any]],
    ordered_source_ids: List[str],
    source_warnings: List[str],
) -> List[str]:
    data = normalize_overview_model_output(data, "reduce")
    errors: List[str] = []
    infra.add_exact_key_errors(data, REDUCE_MODEL_KEYS, "$", errors)

    for key in ("meeting_title", "overall_topic", "executive_summary"):
        validate_string(
            data.get(key),
            f"$.{key}",
            errors,
            non_empty=bool(ordered_source_ids),
        )

    warnings = data.get("warnings")
    infra.validate_string_list(warnings, "$.warnings", errors)

    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        errors.append("$.chapters must be an array")
        chapters = []

    order = {source_id: index for index, source_id in enumerate(ordered_source_ids)}
    source_groups: Dict[str, int] = {}
    for chapter_index, chapter in enumerate(chapters):
        path = f"$.chapters[{chapter_index}]"
        if not isinstance(chapter, dict):
            errors.append(f"{path} must be an object")
            continue
        infra.add_exact_key_errors(chapter, REDUCE_CHAPTER_KEYS, path, errors)
        validate_string(chapter.get("title"), f"{path}.title", errors, non_empty=True)
        validate_string(chapter.get("summary"), f"{path}.summary", errors)
        infra.validate_string_list(chapter.get("key_points"), f"{path}.key_points", errors)
        source_ids = normalize_source_id_list(chapter.get("source_ids"))
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"{path}.source_ids must be a non-empty string array")
            continue

        local_seen: set[str] = set()
        positions: List[int] = []
        for source_index, source_id in enumerate(source_ids):
            source_path = f"{path}.source_ids[{source_index}]"
            if not isinstance(source_id, str):
                errors.append(f"{source_path} must be a string")
                continue
            if source_id in local_seen:
                errors.append(f"{source_path} duplicates source {source_id}")
                continue
            local_seen.add(source_id)
            if source_id not in source_lookup:
                errors.append(f"{source_path} references unknown source {source_id}")
                continue
            if source_id in source_groups:
                errors.append(
                    f"{source_path} reuses source {source_id} from chapter "
                    f"{source_groups[source_id]}"
                )
            else:
                source_groups[source_id] = chapter_index
            positions.append(order[source_id])

        if positions:
            unique_positions = sorted(set(positions))
            expected_positions = list(range(unique_positions[0], unique_positions[-1] + 1))
            if unique_positions != expected_positions:
                errors.append(f"{path}.source_ids must form one contiguous source range")

    missing = [source_id for source_id in ordered_source_ids if source_id not in source_groups]
    if missing:
        errors.append(f"$.chapters missing source_ids: {', '.join(missing)}")

    return errors


def materialize_reduce_output(
    data: Dict[str, Any],
    source_lookup: Dict[str, Dict[str, Any]],
    ordered_source_ids: List[str],
    source_warnings: List[str],
    turns: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    data = normalize_overview_model_output(data, "reduce")
    errors: List[str] = []
    order = {source_id: index for index, source_id in enumerate(ordered_source_ids)}
    output: Dict[str, Any] = {
        "schema_version": "meeting_overview_v0",
        "meeting_title": data.get("meeting_title"),
        "overall_topic": data.get("overall_topic"),
        "executive_summary": data.get("executive_summary"),
        "chapters": [],
        "warnings": list(source_warnings),
    }

    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        errors.append("$.chapters must be an array")
        chapters = []

    converted: List[Dict[str, Any]] = []
    used_turn_ids: Dict[int, int] = {}
    for chapter_index, chapter in enumerate(chapters):
        path = f"$.chapters[{chapter_index}]"
        if not isinstance(chapter, dict):
            errors.append(f"{path} must be an object")
            continue
        source_ids = normalize_source_id_list(chapter.get("source_ids"))
        if not isinstance(source_ids, list):
            source_ids = []
        valid_sources = [
            source_id for source_id in source_ids
            if isinstance(source_id, str) and source_id in source_lookup
        ]
        valid_sources.sort(key=lambda source_id: order[source_id])
        combined_turn_ids: List[int] = []
        for source_id in valid_sources:
            combined_turn_ids.extend(source_lookup[source_id].get("turn_ids", []))
        turn_ids, start, end = materialize_turn_ids(
            combined_turn_ids, turns, f"{path}.source_ids", errors
        )
        for turn_id in turn_ids:
            if turn_id in used_turn_ids:
                errors.append(
                    f"{path} resolves turn {turn_id} already used by chapter "
                    f"{used_turn_ids[turn_id]}"
                )
            else:
                used_turn_ids[turn_id] = chapter_index
        converted.append({
            "title": chapter.get("title"),
            "start": start,
            "end": end,
            "summary": chapter.get("summary"),
            "key_points": chapter.get("key_points"),
            "turn_ids": turn_ids,
        })

    converted.sort(key=lambda item: (float(item["start"]), float(item["end"])))
    output["chapters"] = converted
    return output, errors


def validate_reduce_model_output(
    data: Any,
    source_lookup: Dict[str, Dict[str, Any]],
    ordered_source_ids: List[str],
    source_warnings: List[str],
    turns: List[Dict[str, Any]],
) -> List[str]:
    if not isinstance(data, dict):
        return ["$ must be an object"]
    errors = validate_reduce_contract(
        data, source_lookup, ordered_source_ids, source_warnings
    )
    if errors:
        return errors
    materialized, materialize_errors = materialize_reduce_output(
        data, source_lookup, ordered_source_ids, source_warnings, turns
    )
    errors.extend(materialize_errors)
    errors.extend(validate_overview_output(materialized, turns))
    return errors


def validate_overview_output(data: Any, turns: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return ["$ must be an object"]
    infra.add_exact_key_errors(data, OVERVIEW_KEYS, "$", errors)
    if data.get("schema_version") != "meeting_overview_v0":
        errors.append("$.schema_version must be meeting_overview_v0")

    chapters = data.get("chapters")
    has_chapters = isinstance(chapters, list) and bool(chapters)
    for key in ("meeting_title", "overall_topic", "executive_summary"):
        validate_string(data.get(key), f"$.{key}", errors, non_empty=has_chapters)

    if not isinstance(chapters, list):
        errors.append("$.chapters must be an array")
        chapters = []

    used_turn_ids: Dict[int, int] = {}
    previous_key: Optional[Tuple[float, float]] = None
    for index, chapter in enumerate(chapters):
        path = f"$.chapters[{index}]"
        if not isinstance(chapter, dict):
            errors.append(f"{path} must be an object")
            continue
        infra.add_exact_key_errors(chapter, OVERVIEW_CHAPTER_KEYS, path, errors)
        validate_string(chapter.get("title"), f"{path}.title", errors, non_empty=True)
        validate_string(chapter.get("summary"), f"{path}.summary", errors)
        infra.validate_string_list(chapter.get("key_points"), f"{path}.key_points", errors)
        turn_ids, expected_start, expected_end = materialize_turn_ids(
            chapter.get("turn_ids"), turns, f"{path}.turn_ids", errors
        )
        if chapter.get("turn_ids") != turn_ids:
            errors.append(f"{path}.turn_ids must be unique and in source order")
        start, end = chapter.get("start"), chapter.get("end")
        if not infra.is_number(start) or not infra.is_number(end):
            errors.append(f"{path}.start/end must be numbers")
        else:
            start_f, end_f = float(start), float(end)
            if start_f < 0 or end_f < start_f:
                errors.append(f"{path} has invalid time range")
            if abs(start_f - expected_start) > 1e-6 or abs(end_f - expected_end) > 1e-6:
                errors.append(f"{path}.start/end must match referenced turns")
            key = (start_f, end_f)
            if previous_key is not None and key < previous_key:
                errors.append("$.chapters must be in chronological order")
            previous_key = key
        for turn_id in turn_ids:
            if turn_id in used_turn_ids:
                errors.append(
                    f"{path}.turn_ids reuses turn {turn_id} from chapter "
                    f"{used_turn_ids[turn_id]}"
                )
            else:
                used_turn_ids[turn_id] = index

    infra.validate_string_list(data.get("warnings"), "$.warnings", errors)
    return errors


def transform_reduce_output(
    data: Dict[str, Any],
    source_lookup: Dict[str, Dict[str, Any]],
    ordered_source_ids: List[str],
    source_warnings: List[str],
    turns: List[Dict[str, Any]],
) -> Dict[str, Any]:
    output, errors = materialize_reduce_output(
        data, source_lookup, ordered_source_ids, source_warnings, turns
    )
    errors.extend(validate_overview_output(output, turns))
    if errors:
        raise ValidationError("; ".join(errors))
    return output


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def clean_heading(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def render_overview_markdown(overview: Dict[str, Any]) -> str:
    title = clean_heading(overview.get("meeting_title")) or "会议纪要概览"
    topic = overview.get("overall_topic") if isinstance(overview.get("overall_topic"), str) else ""
    summary = overview.get("executive_summary") if isinstance(overview.get("executive_summary"), str) else ""
    lines = [
        f"# {title}",
        "",
        "## 总体主题",
        "",
        topic or "暂无。",
        "",
        "## 总体摘要",
        "",
        summary or "暂无。",
        "",
        "## 章节纪要",
        "",
    ]

    chapters = overview.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        lines.extend(["暂无可用章节。", ""])
    else:
        for index, chapter in enumerate(chapters, 1):
            if not isinstance(chapter, dict):
                continue
            chapter_title = clean_heading(chapter.get("title")) or f"章节 {index}"
            start = format_timestamp(float(chapter.get("start", 0.0)))
            end = format_timestamp(float(chapter.get("end", 0.0)))
            lines.extend([
                f"### {index}. {chapter_title}",
                "",
                f"- 时间：`{start}` - `{end}`",
            ])
            turn_ids = chapter.get("turn_ids")
            if isinstance(turn_ids, list) and turn_ids:
                lines.append("- 证据 Turn：" + ", ".join(str(item) for item in turn_ids))
            lines.extend(["", chapter.get("summary") or "暂无摘要。", ""])
            key_points = chapter.get("key_points")
            if isinstance(key_points, list) and key_points:
                lines.extend(["关键要点：", ""])
                lines.extend(f"- {item}" for item in key_points if isinstance(item, str))
                lines.append("")

    warnings = overview.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["## 警告", ""])
        lines.extend(f"- {warning}" for warning in warnings if isinstance(warning, str))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def placeholder_for_failed_window(window: Dict[str, Any], error: str) -> Dict[str, Any]:
    return {
        "schema_version": "meeting_overview_map_v0",
        "window_id": window["window_id"],
        "time_range": {"start": window["start"], "end": window["end"]},
        "chapters": [],
        "warnings": [
            f"MAP window {window['window_id']} failed for "
            f"{window['start']:.3f}-{window['end']:.3f}: {error}"
        ],
    }


def is_failed_map_placeholder(value: Dict[str, Any]) -> bool:
    chapters = value.get("chapters") if isinstance(value.get("chapters"), list) else []
    warnings = value.get("warnings") if isinstance(value.get("warnings"), list) else []
    return not chapters and any(
        isinstance(warning, str)
        and warning.startswith("MAP window ")
        and " failed " in warning
        for warning in warnings
    )


def run_map_stage(
    args: argparse.Namespace,
    plan: Dict[str, Any],
    turns: List[Dict[str, Any]],
    prompt_template: str,
    run_dir: Path,
    repeat: int,
    monitor: infra.MemoryMonitor,
    plan_path: Path,
) -> List[Dict[str, Any]]:
    results_path = run_dir / "map_results.jsonl"
    latest = infra.latest_map_records(results_path) if args.resume else {}
    queue = [window for window in plan["windows"] if window.get("active", True)]
    outputs: Dict[int, Dict[str, Any]] = {}
    for window in queue:
        previous = latest.get(window["window_id"])
        if previous and previous.get("status") == "ok" and isinstance(previous.get("output"), dict):
            outputs[window["window_id"]] = previous["output"]

    while queue:
        window = queue.pop(0)
        window_id = window["window_id"]
        previous = latest.get(window_id)
        if previous and previous.get("status") == "ok" and isinstance(previous.get("output"), dict):
            outputs[window_id] = previous["output"]
            continue

        prompt = infra.render_map_prompt(prompt_template, window)
        artifact_dir = run_dir / "map" / "windows" / f"window_{window_id:04d}"
        allowed_units = infra.turns_for_window(window, plan["units"])
        allowed_ids = {item["id"] for item in allowed_units}
        allowed = [turn for turn in turns if turn["id"] in allowed_ids]
        validator = lambda value, w=window, t=allowed: validate_map_model_output(value, w, t)
        transform = lambda value, w=window, t=allowed: transform_map_output(value, w, t)
        try:
            output, metadata = infra.call_model(
                args,
                prompt,
                args.map_max_tokens,
                artifact_dir,
                {"phase": "map", "repeat": repeat, "window_id": window_id},
                validator,
                monitor,
                transform,
            )
            record = {
                "timestamp": time.time(),
                "status": "ok",
                "window_id": window_id,
                "repeat": repeat,
                "metadata": metadata,
                "output": output,
            }
            infra.append_jsonl(results_path, record)
            latest[window_id] = record
            outputs[window_id] = output
        except PromptBudgetExceeded as exc:
            active_count = sum(item.get("active", True) for item in plan["windows"])
            if len(window["unit_indexes"]) < 2 or active_count >= args.max_map_windows:
                error = str(exc)
                if active_count >= args.max_map_windows:
                    error += f"; active MAP window limit {args.max_map_windows} reached"
                placeholder = placeholder_for_failed_window(window, error)
                record = {
                    "timestamp": time.time(),
                    "status": "failed",
                    "window_id": window_id,
                    "repeat": repeat,
                    "error": error,
                    "output": placeholder,
                }
                infra.append_jsonl(results_path, record)
                outputs[window_id] = placeholder
                continue
            children = infra.split_window(plan, window)
            infra.write_json(plan_path, plan)
            infra.append_jsonl(results_path, {
                "timestamp": time.time(),
                "status": "split",
                "window_id": window_id,
                "repeat": repeat,
                "error": str(exc),
                "split_into": [child["window_id"] for child in children],
            })
            queue = children + queue
        except ValidationError as exc:
            placeholder = placeholder_for_failed_window(window, str(exc))
            infra.append_jsonl(results_path, {
                "timestamp": time.time(),
                "status": "failed",
                "window_id": window_id,
                "repeat": repeat,
                "error": str(exc),
                "output": placeholder,
            })
            outputs[window_id] = placeholder

    active_windows = sorted(
        (window for window in plan["windows"] if window.get("active", True)),
        key=lambda item: (float(item["start"]), float(item["end"]), item["window_id"]),
    )
    return [
        outputs[window["window_id"]]
        for window in active_windows
        if window["window_id"] in outputs
    ]


def run_reduce_stage(
    args: argparse.Namespace,
    map_results: List[Dict[str, Any]],
    turns: List[Dict[str, Any]],
    prompt_template: str,
    run_dir: Path,
    repeat: int,
    monitor: infra.MemoryMonitor,
) -> Dict[str, Any]:
    if not map_results:
        raise ValidationError("no MAP results are available for REDUCE")

    current = sorted(map_results, key=lambda value: overview_time_range(value))
    level = 1
    while True:
        groups = [
            current[index:index + args.reduce_group_size]
            for index in range(0, len(current), args.reduce_group_size)
        ]
        next_level: List[Dict[str, Any]] = []
        for group in groups:
            pending_groups = [group]
            while pending_groups:
                current_group = pending_groups.pop(0)
                prompt_values, source_lookup, source_ids, source_warnings = build_reduce_sources(
                    current_group, turns
                )
                compact = json.dumps(prompt_values, ensure_ascii=False, separators=(",", ":"))
                prompt = prompt_template.replace("{map_results}", compact)
                dynamic_group = len(next_level) + 1
                artifact_dir = run_dir / "reduce" / f"level_{level:02d}_group_{dynamic_group:03d}"
                validator = (
                    lambda value, lookup=source_lookup, ids=source_ids,
                    warnings=source_warnings, source_turns=turns:
                    validate_reduce_model_output(
                        value, lookup, ids, warnings, source_turns
                    )
                )
                transform = (
                    lambda value, lookup=source_lookup, ids=source_ids,
                    warnings=source_warnings, source_turns=turns:
                    transform_reduce_output(
                        value, lookup, ids, warnings, source_turns
                    )
                )
                try:
                    output, _ = infra.call_model(
                        args,
                        prompt,
                        args.reduce_max_tokens,
                        artifact_dir,
                        {
                            "phase": "reduce",
                            "repeat": repeat,
                            "level": level,
                            "group": dynamic_group,
                        },
                        validator,
                        monitor,
                        transform,
                    )
                except PromptBudgetExceeded as exc:
                    if len(current_group) == 1:
                        raise ValidationError(
                            f"single REDUCE input exceeds prompt budget: {exc.prompt_tokens}"
                        ) from exc
                    midpoint = len(current_group) // 2
                    pending_groups = [
                        current_group[:midpoint], current_group[midpoint:]
                    ] + pending_groups
                    continue

                source_ranges = [overview_time_range(value) for value in current_group]
                output["_source_time_range"] = {
                    "start": min((start for start, _ in source_ranges), default=0.0),
                    "end": max((end for _, end in source_ranges), default=0.0),
                }
                next_level.append(output)

        if len(next_level) == 1:
            final = dict(next_level[0])
            final.pop("_source_time_range", None)
            errors = validate_overview_output(final, turns)
            if errors:
                raise ValidationError("; ".join(errors))
            return final
        if len(next_level) >= len(current):
            raise ValidationError(
                "REDUCE tree did not shrink; increase --reduce-group-size or prompt budget"
            )
        current = sorted(next_level, key=lambda value: overview_time_range(value))
        level += 1
        if level > 16:
            raise ValidationError("REDUCE tree exceeded 16 levels")


def build_snapshot(
    args: argparse.Namespace,
    turns_path: Path,
    map_prompt: Path,
    reduce_prompt: Path,
    schema_paths: List[Path],
    llm_files: Optional[Dict[str, Path]],
) -> Dict[str, Any]:
    model_files = {}
    for key, path in (llm_files or {}).items():
        model_files[key] = {"path": str(path), "size": path.stat().st_size}
    infra_path = Path(infra.__file__).resolve()
    return {
        "schema_version": "meeting_overview_input_snapshot_v0",
        "turns_file": str(turns_path),
        "turns_sha256": infra.sha256_file(turns_path),
        "map_prompt": str(map_prompt),
        "map_prompt_sha256": infra.sha256_file(map_prompt),
        "reduce_prompt": str(reduce_prompt),
        "reduce_prompt_sha256": infra.sha256_file(reduce_prompt),
        "schemas": {
            path.name: {"path": str(path), "sha256": infra.sha256_file(path)}
            for path in schema_paths
        },
        "infrastructure_runner": {
            "path": str(infra_path),
            "sha256": infra.sha256_file(infra_path),
        },
        "model_files": model_files,
        "ctx": args.ctx,
        "predict": args.predict,
        "map_target_chars": args.map_target_chars,
        "map_max_turns": args.map_max_turns,
        "max_map_windows": args.max_map_windows,
        "overlap_turns": args.overlap_turns,
        "max_prompt_tokens": args.max_prompt_tokens,
        "chars_to_tokens_ratio": args.chars_to_tokens_ratio,
        "map_max_tokens": args.map_max_tokens,
        "reduce_max_tokens": args.reduce_max_tokens,
        "reduce_group_size": args.reduce_group_size,
    }


def verify_resume_snapshot(path: Path, current: Dict[str, Any]) -> None:
    if not path.is_file():
        return
    previous = json.loads(infra.read_text(path))
    for key in (
        "turns_sha256", "map_prompt_sha256", "reduce_prompt_sha256", "schemas",
        "infrastructure_runner", "model_files", "ctx", "predict",
        "map_target_chars", "map_max_turns", "max_map_windows", "overlap_turns",
        "max_prompt_tokens", "chars_to_tokens_ratio", "map_max_tokens",
        "reduce_max_tokens", "reduce_group_size",
    ):
        if previous.get(key) != current.get(key):
            raise ValidationError(
                f"resume snapshot mismatch for {key}: "
                f"{previous.get(key)!r} != {current.get(key)!r}"
            )


def load_or_create_plan(
    path: Path,
    turns: List[Dict[str, Any]],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    return infra.load_or_create_plan(path, turns, args)


def run_repeat(
    args: argparse.Namespace,
    plan: Dict[str, Any],
    turns: List[Dict[str, Any]],
    map_prompt: str,
    reduce_prompt: str,
    run_dir: Path,
    repeat: int,
    monitor: infra.MemoryMonitor,
    plan_path: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    repeat_plan = json.loads(json.dumps(plan))
    repeat_plan_path = plan_path if repeat == 1 else run_dir / "window_plan.json"
    if repeat > 1:
        infra.write_json(repeat_plan_path, repeat_plan)
    map_results = run_map_stage(
        args, repeat_plan, turns, map_prompt, run_dir, repeat, monitor, repeat_plan_path
    )
    failed_map_count = sum(is_failed_map_placeholder(value) for value in map_results)
    overview = run_reduce_stage(
        args, map_results, turns, reduce_prompt, run_dir, repeat, monitor
    )
    overview_path = run_dir / "overview.json"
    markdown_path = run_dir / "overview.md"
    infra.write_json(overview_path, overview)
    infra.write_text(markdown_path, render_overview_markdown(overview))
    repeat_status = "pass" if failed_map_count == 0 else "partial"
    repeat_result = {
        "status": repeat_status,
        "repeat": repeat,
        "map_result_count": len(map_results),
        "failed_map_count": failed_map_count,
        "overview": str(overview_path),
        "markdown": str(markdown_path),
    }
    infra.write_json(run_dir / "result.json", repeat_result)
    return overview, repeat_result


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RK1828 structured ASR turns -> chronological meeting overview"
    )
    parser.add_argument("--turns-file", default=DEFAULT_TURNS)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model-name", default="default")
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--predict", type=int, default=1024)
    parser.add_argument("--map-max-tokens", type=int, default=512)
    parser.add_argument("--reduce-max-tokens", type=int, default=1024)
    parser.add_argument("--map-target-chars", type=int, default=4500)
    parser.add_argument("--map-max-turns", type=int, default=40)
    parser.add_argument(
        "--max-map-windows",
        type=int,
        default=16,
        help="Hard cap after automatic prompt-budget splits",
    )
    parser.add_argument("--max-prompt-tokens", type=int, default=6600)
    parser.add_argument(
        "--chars-to-tokens-ratio",
        type=float,
        default=0.85,
        help="Conservative preflight estimate used before sending a request",
    )
    parser.add_argument("--overlap-turns", type=int, default=1)
    parser.add_argument("--reduce-group-size", type=int, default=5)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--stability-repeat", type=int, default=1)
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument("--idle-seconds", type=float, default=0.5)
    parser.add_argument("--leak-threshold-mb", type=float, default=128.0)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--reuse-server", action="store_true")
    parser.add_argument("--keep-server", action="store_true")
    parser.add_argument("--allow-resource-overlap", action="store_true")
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument(
        "--response-format-json-object",
        dest="response_format_json_object",
        action="store_true",
        default=True,
    )
    parser.add_argument(
        "--no-response-format-json-object",
        dest="response_format_json_object",
        action="store_false",
    )
    parser.add_argument("--server-temp", type=float)
    parser.add_argument("--server-top-k", type=int)
    parser.add_argument("--server-top-p", type=float)
    parser.add_argument("--server-repeat-penalty", type=float)
    parser.add_argument("--llm-rknn")
    parser.add_argument("--llm-weight")
    parser.add_argument("--llm-vocab")
    parser.add_argument("--llm-embed")
    parser.add_argument("--prompt-map")
    parser.add_argument("--prompt-reduce")
    parser.add_argument("--schema-dir")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    infra.validate_args(args)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "result.json"
    started = time.time()
    process: Optional[subprocess.Popen[Any]] = None
    monitor = infra.MemoryMonitor(out_dir, args.sample_interval, args.leak_threshold_mb)
    server_log = out_dir / "server.log"

    try:
        turns_path = Path(args.turns_file)
        turns = infra.load_turns(turns_path)
        map_prompt_path = infra.resolve_asset(
            args.prompt_map, "prompts/meeting_overview_map_v0_zh.txt"
        )
        reduce_prompt_path = infra.resolve_asset(
            args.prompt_reduce, "prompts/meeting_overview_reduce_v0_zh.txt"
        )
        map_prompt = infra.read_text(map_prompt_path)
        reduce_prompt = infra.read_text(reduce_prompt_path)
        for placeholder in ("{window_id}", "{window_start}", "{window_end}", "{transcript}"):
            if placeholder not in map_prompt:
                raise ValidationError(f"MAP prompt is missing required placeholder {placeholder}")
        if "{map_results}" not in reduce_prompt:
            raise ValidationError("REDUCE prompt is missing required placeholder {map_results}")

        schema_dir = Path(args.schema_dir) if args.schema_dir else infra.resolve_asset(
            None, "schemas/meeting_overview_v0.schema.json"
        ).parent
        schema_paths = [
            schema_dir / "meeting_transcript_turns_v0.schema.json",
            schema_dir / "meeting_overview_map_v0.schema.json",
            schema_dir / "meeting_overview_v0.schema.json",
        ]
        for schema_path in schema_paths:
            infra.require_file(schema_path, f"schema {schema_path.name}")
            json.loads(infra.read_text(schema_path))

        source_turns_path = out_dir / "source_turns.json"
        infra.write_json(source_turns_path, turns)
        plan_path = out_dir / "window_plan.json"
        plan = load_or_create_plan(plan_path, turns, args)
        infra.write_text(
            out_dir / "canonical_transcript.txt",
            "\n".join(infra.canonical_unit_line(unit) for unit in plan["units"]) + "\n",
        )

        llm_files = None if args.plan_only else infra.discover_llm_files(args)
        snapshot = build_snapshot(
            args,
            turns_path,
            map_prompt_path,
            reduce_prompt_path,
            schema_paths,
            llm_files,
        )
        snapshot_path = out_dir / "input_snapshot.json"
        if args.resume and not args.plan_only and not args.reuse_server:
            verify_resume_snapshot(snapshot_path, snapshot)
        infra.write_json(snapshot_path, snapshot)

        if args.plan_only:
            infra.write_json(result_path, {
                "status": "planned",
                "turn_count": len(turns),
                "unit_count": len(plan["units"]),
                "window_count": len([
                    window for window in plan["windows"] if window.get("active", True)
                ]),
                "window_plan": str(plan_path),
                "source_turns": str(source_turns_path),
            })
            print(f"PLANNED: {result_path}")
            return 0

        conflicts = infra.find_resource_conflicts(allow_server=args.reuse_server)
        if conflicts and not args.allow_resource_overlap:
            raise EnvironmentError(
                "AI resource conflict detected; stop ASR/LLM processes or pass "
                f"--allow-resource-overlap explicitly: {conflicts}"
            )

        monitor.start()
        monitor.record_anchor("before_server_start")
        process, server_pid = infra.start_server(args, llm_files or {}, server_log)
        if server_pid is None:
            server_pid = infra.find_server_pid(args.port)
        monitor.set_server_pid(server_pid)
        monitor.record_anchor("after_server_ready", server_pid=server_pid)

        final_overview: Optional[Dict[str, Any]] = None
        repeat_results = []
        for repeat in range(1, args.stability_repeat + 1):
            run_dir = out_dir if repeat == 1 else out_dir / "repeats" / f"repeat_{repeat:03d}"
            repeat_started = time.time()
            repeat_args = argparse.Namespace(**vars(args))
            if repeat > 1:
                repeat_args.resume = False
            final_overview, repeat_result = run_repeat(
                repeat_args,
                plan,
                turns,
                map_prompt,
                reduce_prompt,
                run_dir,
                repeat,
                monitor,
                plan_path,
            )
            repeat_results.append({
                **repeat_result,
                "elapsed_sec": round(time.time() - repeat_started, 3),
            })

        if final_overview is None:
            raise ValidationError("no final overview was generated")
        overview_path = out_dir / "overview.json"
        markdown_path = out_dir / "overview.md"
        infra.write_json(overview_path, final_overview)
        infra.write_text(markdown_path, render_overview_markdown(final_overview))
        overall_status = (
            "pass" if all(item["status"] == "pass" for item in repeat_results)
            else "partial"
        )
        result = {
            "status": overall_status,
            "turn_count": len(turns),
            "unit_count": len(plan["units"]),
            "active_window_count": len([
                window for window in plan["windows"] if window.get("active", True)
            ]),
            "stability_repeat": args.stability_repeat,
            "repeats": repeat_results,
            "elapsed_sec": round(time.time() - started, 3),
            "overview": str(overview_path),
            "markdown": str(markdown_path),
            "source_turns": str(source_turns_path),
        }
        infra.write_json(result_path, result)
        print(f"{overall_status.upper()}: {result_path}")
        return 0
    except MinutesError as exc:
        infra.write_json(result_path, {
            "status": "fail",
            "error": str(exc),
            "error_type": type(exc).__name__,
            "exit_code": exc.exit_code,
            "elapsed_sec": round(time.time() - started, 3),
        })
        print(f"FAIL: {exc}", file=sys.stderr)
        print(f"See: {result_path}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - preserve top-level result
        infra.write_json(result_path, {
            "status": "fail",
            "error": str(exc),
            "error_type": type(exc).__name__,
            "exit_code": infra.EXIT_RUNTIME,
            "elapsed_sec": round(time.time() - started, 3),
        })
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"See: {result_path}", file=sys.stderr)
        return infra.EXIT_RUNTIME
    finally:
        if monitor.thread is not None:
            monitor.record_anchor("before_server_stop")
        infra.stop_server(process, args.keep_server)
        if monitor.thread is not None:
            monitor.set_server_pid(None)
            monitor.record_anchor("after_server_stop")
            monitor.stop()
            summary = infra.summarize_memory(
                out_dir, server_log, args.leak_threshold_mb
            )
            infra.write_json(out_dir / "memory_summary.json", summary)


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
