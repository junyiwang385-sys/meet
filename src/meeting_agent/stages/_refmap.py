"""ref/speaker 紧凑化：把 seg-000123 → r123、speaker_1 → sp1，压 prompt token。

从 product_summary.py 拆出（纯函数、无内部依赖）。forward=canonical→compact，
reverse=compact→canonical；_compactize_payload/_expand_payload 按 key 递归替换。
"""

from __future__ import annotations

import re
from typing import Any


def _compact_ref_name(segment_id: str, fallback_index: int) -> str:
    match = re.fullmatch(r"seg-(\d+)", str(segment_id))
    if match:
        return f"r{int(match.group(1))}"
    return f"r{fallback_index}"


def _build_compact_ref_map(
    segments: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    forward: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for index, segment in enumerate(segments, 1):
        canonical = str(segment["segment_id"])
        compact = _compact_ref_name(canonical, index)
        if compact in reverse and reverse[compact] != canonical:
            compact = f"r{index}"
        forward[canonical] = compact
        reverse[compact] = canonical
    return forward, reverse


def _build_compact_ref_map_from_ids(
    segment_ids: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    return _build_compact_ref_map(
        [{"segment_id": segment_id} for segment_id in segment_ids]
    )


def _build_compact_speaker_map(
    speaker_ids: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    forward: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for index, canonical in enumerate(dict.fromkeys(str(item) for item in speaker_ids), 1):
        match = re.fullmatch(r"speaker_(\d+)", canonical)
        compact = f"sp{int(match.group(1))}" if match else f"sp{index}"
        if compact in reverse and reverse[compact] != canonical:
            compact = f"sp{index}"
        forward[canonical] = compact
        reverse[compact] = canonical
    return forward, reverse


def _compactize_payload(
    value: Any,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
    key: str | None = None,
) -> Any:
    ref_keys = {
        "segment_id",
        "start_ref",
        "end_ref",
        "core_start_ref",
        "core_end_ref",
        "carryover_start_ref",
        "refs",
        "key_refs",
    }
    speaker_keys = {"speaker_id", "owner"}
    if isinstance(value, dict):
        return {
            item_key: _compactize_payload(item_value, ref_map, speaker_map, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_compactize_payload(item, ref_map, speaker_map, key) for item in value]
    if isinstance(value, str):
        if key in ref_keys:
            return ref_map.get(value, value)
        if key in speaker_keys:
            return speaker_map.get(value, value)
    return value


def _expand_payload(
    value: Any,
    ref_map: dict[str, str],
    speaker_map: dict[str, str],
    key: str | None = None,
) -> Any:
    ref_keys = {
        "segment_id",
        "start_ref",
        "end_ref",
        "core_start_ref",
        "core_end_ref",
        "carryover_start_ref",
        "refs",
        "key_refs",
    }
    speaker_keys = {"speaker_id", "owner"}
    if isinstance(value, dict):
        return {
            item_key: _expand_payload(item_value, ref_map, speaker_map, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_expand_payload(item, ref_map, speaker_map, key) for item in value]
    if isinstance(value, str):
        if key in ref_keys:
            return ref_map.get(value, value)
        if key in speaker_keys:
            return speaker_map.get(value, value)
    return value
