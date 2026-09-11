"""Deterministic Timeline metrics for end-to-end Meeting_Agent evaluation."""

from __future__ import annotations

import re
from typing import Any

_TEXT_RE = re.compile(r"[0-9a-zA-Z一-鿿]")


def normalize_text(value: Any) -> str:
    return "".join(_TEXT_RE.findall(str(value or "").lower()))


def edit_distance(left: str, right: str) -> int:
    """Return exact Levenshtein distance using a bit-parallel algorithm."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    if len(left) > len(right):
        left, right = right, left

    pattern_length = len(left)
    high_bit = 1 << (pattern_length - 1)
    mask = (1 << pattern_length) - 1
    char_masks: dict[str, int] = {}
    for index, char in enumerate(left):
        char_masks[char] = char_masks.get(char, 0) | (1 << index)

    positive = mask
    negative = 0
    score = pattern_length
    for char in right:
        equal = char_masks.get(char, 0)
        vertical = equal | negative
        horizontal = (((equal & positive) + positive) ^ positive) | equal
        positive_horizontal = negative | ~(horizontal | positive)
        negative_horizontal = positive & horizontal
        if positive_horizontal & high_bit:
            score += 1
        elif negative_horizontal & high_bit:
            score -= 1
        positive_horizontal = ((positive_horizontal << 1) | 1) & mask
        negative_horizontal = (negative_horizontal << 1) & mask
        positive = (negative_horizontal | ~(vertical | positive_horizontal)) & mask
        negative = positive_horizontal & vertical
    return score


def _overlap_ms(left: dict[str, Any], right: dict[str, Any]) -> int:
    return max(
        0,
        min(int(left["end_ms"]), int(right["end_ms"]))
        - max(int(left["start_ms"]), int(right["start_ms"])),
    )


def _union_intervals(segments: list[dict[str, Any]]) -> list[tuple[int, int]]:
    spans = sorted(
        (int(item["start_ms"]), int(item["end_ms"]))
        for item in segments
        if int(item["end_ms"]) > int(item["start_ms"])
    )
    if not spans:
        return []
    merged = [spans[0]]
    for start, end in spans[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _interval_duration(intervals: list[tuple[int, int]]) -> int:
    return sum(end - start for start, end in intervals)


def _intersection_duration(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
) -> int:
    total = 0
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_start, left_end = left[left_index]
        right_start, right_end = right[right_index]
        total += max(0, min(left_end, right_end) - max(left_start, right_start))
        if left_end <= right_end:
            left_index += 1
        else:
            right_index += 1
    return total


def _hungarian_max(weights: list[list[int]]) -> list[int | None]:
    """Return a maximum-weight column assignment for every input row."""
    if not weights:
        return []
    row_count = len(weights)
    column_count = max((len(row) for row in weights), default=0)
    if column_count == 0:
        return [None] * row_count
    size = max(row_count, column_count)
    maximum = max((value for row in weights for value in row), default=0)
    cost = [
        [
            maximum
            - (
                weights[row][column]
                if row < row_count and column < len(weights[row])
                else 0
            )
            for column in range(size)
        ]
        for row in range(size)
    ]

    u = [0] * (size + 1)
    v = [0] * (size + 1)
    matched_row = [0] * (size + 1)
    previous_column = [0] * (size + 1)
    for row in range(1, size + 1):
        matched_row[0] = row
        column = 0
        minimum = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[column] = True
            active_row = matched_row[column]
            delta = float("inf")
            next_column = 0
            for candidate in range(1, size + 1):
                if used[candidate]:
                    continue
                current = (
                    cost[active_row - 1][candidate - 1] - u[active_row] - v[candidate]
                )
                if current < minimum[candidate]:
                    minimum[candidate] = current
                    previous_column[candidate] = column
                if minimum[candidate] < delta:
                    delta = minimum[candidate]
                    next_column = candidate
            for candidate in range(size + 1):
                if used[candidate]:
                    u[matched_row[candidate]] += delta
                    v[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            prior = previous_column[column]
            matched_row[column] = matched_row[prior]
            column = prior
            if column == 0:
                break

    assignment: list[int | None] = [None] * row_count
    for column in range(1, size + 1):
        row = matched_row[column] - 1
        if 0 <= row < row_count and column - 1 < column_count:
            assignment[row] = column - 1
    return assignment


def speaker_mapping(
    predicted: list[dict[str, Any]], reference: list[dict[str, Any]]
) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
    predicted_labels = sorted(
        {
            str(item["speaker_id"])
            for item in predicted
            if str(item.get("speaker_id", "")).lower() != "unknown"
        }
    )
    reference_labels = sorted({str(item["speaker_id"]) for item in reference})
    matrix = {
        predicted_label: {reference_label: 0 for reference_label in reference_labels}
        for predicted_label in predicted_labels
    }
    for predicted_item in predicted:
        predicted_label = str(predicted_item.get("speaker_id", ""))
        if predicted_label not in matrix:
            continue
        for reference_item in reference:
            overlap = _overlap_ms(predicted_item, reference_item)
            if overlap:
                matrix[predicted_label][str(reference_item["speaker_id"])] += overlap
    weights = [
        [
            matrix[predicted_label][reference_label]
            for reference_label in reference_labels
        ]
        for predicted_label in predicted_labels
    ]
    assignment = _hungarian_max(weights)
    mapping = {}
    for row, column in enumerate(assignment):
        if column is None or column >= len(reference_labels):
            continue
        if weights[row][column] > 0:
            mapping[predicted_labels[row]] = reference_labels[column]
    return mapping, matrix


def _active_speakers(segments: list[dict[str, Any]], timestamp_ms: int) -> set[str]:
    return {
        str(item["speaker_id"])
        for item in segments
        if int(item["start_ms"]) <= timestamp_ms < int(item["end_ms"])
    }


def evaluate_timelines(
    predicted: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    *,
    activity_segments: list[dict[str, Any]] | None = None,
    sample_step_ms: int = 100,
) -> dict[str, Any]:
    if sample_step_ms <= 0:
        raise ValueError("sample_step_ms must be positive")
    if not reference:
        raise ValueError("reference Timeline is empty")

    predicted_text = normalize_text(
        "".join(str(item.get("text") or "") for item in predicted)
    )
    reference_text = normalize_text(
        "".join(str(item.get("text") or "") for item in reference)
    )
    distance = edit_distance(reference_text, predicted_text)
    activity = activity_segments if activity_segments is not None else predicted

    predicted_speech = _union_intervals(activity)
    reference_speech = _union_intervals(reference)
    predicted_speech_ms = _interval_duration(predicted_speech)
    reference_speech_ms = _interval_duration(reference_speech)
    overlap_speech_ms = _intersection_duration(predicted_speech, reference_speech)

    mapping, overlap_matrix = speaker_mapping(activity, reference)
    end_ms = max(
        [int(item["end_ms"]) for item in activity + reference],
        default=0,
    )
    speaker_evaluated = 0
    speaker_hits = 0
    timestamp = sample_step_ms // 2
    while timestamp < end_ms:
        reference_active = _active_speakers(reference, timestamp)
        predicted_active = _active_speakers(activity, timestamp)
        predicted_known = {
            item for item in predicted_active if item.lower() != "unknown"
        }
        if reference_active and predicted_known:
            speaker_evaluated += 1
            mapped = {mapping.get(item, f"unmapped:{item}") for item in predicted_known}
            if mapped & reference_active:
                speaker_hits += 1
        timestamp += sample_step_ms

    unknown = [
        item
        for item in activity
        if str(item.get("speaker_id", "")).lower() == "unknown"
    ]
    unknown_ms = _interval_duration(_union_intervals(unknown))
    predicted_end_ms = max((int(item["end_ms"]) for item in activity), default=0)
    reference_end_ms = max(int(item["end_ms"]) for item in reference)
    predicted_speakers = sorted({str(item["speaker_id"]) for item in activity})
    reference_speakers = sorted({str(item["speaker_id"]) for item in reference})
    predicted_known_speakers = [
        item for item in predicted_speakers if item.lower() != "unknown"
    ]

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 6) if denominator else None

    return {
        "status": "success",
        "text": {
            "reference_chars": len(reference_text),
            "predicted_chars": len(predicted_text),
            "edit_distance": distance,
            "cer": ratio(distance, len(reference_text)),
        },
        "speech": {
            "reference_speech_ms": reference_speech_ms,
            "predicted_speech_ms": predicted_speech_ms,
            "overlap_speech_ms": overlap_speech_ms,
            "recall": ratio(overlap_speech_ms, reference_speech_ms),
            "precision": ratio(overlap_speech_ms, predicted_speech_ms),
        },
        "speaker": {
            "reference_count": len(reference_speakers),
            "predicted_count": len(predicted_known_speakers),
            "count_error": len(predicted_known_speakers) - len(reference_speakers),
            "absolute_count_error": abs(
                len(predicted_known_speakers) - len(reference_speakers)
            ),
            "mapping_predicted_to_reference": mapping,
            "overlap_matrix_ms": overlap_matrix,
            "evaluated_sample_count": speaker_evaluated,
            "accuracy_on_overlap": ratio(speaker_hits, speaker_evaluated),
        },
        "timeline": {
            "reference_segment_count": len(reference),
            "predicted_segment_count": len(activity),
            "predicted_nonempty_timeline_segment_count": len(predicted),
            "predicted_empty_text_count": sum(
                not str(item.get("text") or "").strip() for item in activity
            ),
            "reference_end_ms": reference_end_ms,
            "predicted_end_ms": predicted_end_ms,
            "duration_difference_ms": predicted_end_ms - reference_end_ms,
            "duration_ratio": ratio(predicted_end_ms, reference_end_ms),
            "unknown_segment_count": len(unknown),
            "unknown_segment_ratio": ratio(len(unknown), len(activity)),
            "unknown_speech_ms": unknown_ms,
            "unknown_speech_ratio": ratio(unknown_ms, predicted_speech_ms),
        },
    }
