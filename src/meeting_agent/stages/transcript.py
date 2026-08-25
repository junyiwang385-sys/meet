"""Canonical transcript construction from Batch ASR artifacts."""

from __future__ import annotations

import math
import pathlib
import re
from typing import Any

from ..storage.artifacts import atomic_write_json, atomic_write_text, load_json


ACCEPTED_STATUSES = {"ok", "transcript_empty"}
WHITESPACE_RE = re.compile(r"\s+")


def normalize_speaker(value: Any) -> str:
    speaker = str(value or "unknown").strip()
    if not speaker or speaker.lower() == "unknown":
        return "unknown"
    return speaker if speaker.startswith("speaker_") else f"speaker_{speaker}"


def seconds_to_ms(value: Any, field: str) -> int:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"invalid {field}: {value!r}")
    return int(round(seconds * 1000.0))


def format_ms(value: int) -> str:
    total_seconds = (value + 500) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m{seconds:02d}s"


def canonicalize_rows(rows: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("segment_transcripts.json must contain a non-empty JSON array")

    seen_indexes: set[int] = set()
    canonical: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"transcript row {position} is not an object")
        try:
            index = int(row["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"transcript row {position} has invalid index") from exc
        if index < 0 or index in seen_indexes:
            raise ValueError(f"duplicate or negative transcript index: {index}")
        seen_indexes.add(index)

        start_ms = seconds_to_ms(row.get("start"), "start")
        end_ms = seconds_to_ms(row.get("end"), "end")
        if end_ms <= start_ms:
            raise ValueError(f"segment {index} has end <= start")

        status = str(row.get("status") or "unknown")
        text = WHITESPACE_RE.sub(" ", str(row.get("text") or "")).strip()
        if status not in ACCEPTED_STATUSES:
            failed.append({"index": index, "status": status, "error": str(row.get("error") or "")})

        canonical.append(
            {
                "segment_id": f"seg-{index:06d}",
                "index": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker_id": normalize_speaker(row.get("speaker")),
                "text": text,
                "status": status,
                "source_job_id": str(row.get("job_id") or ""),
                "source_audio_name": str(row.get("audio_name") or pathlib.Path(str(row.get("audio") or "")).name),
            }
        )

    if failed:
        raise ValueError(f"ASR contains failed segments: {failed[:10]}")

    canonical.sort(key=lambda item: (item["start_ms"], item["end_ms"], item["index"]))
    nonempty = [item for item in canonical if item["text"]]
    speakers = sorted({item["speaker_id"] for item in canonical})
    stats = {
        "segment_count": len(canonical),
        "nonempty_segment_count": len(nonempty),
        "empty_segment_count": len(canonical) - len(nonempty),
        "speaker_ids": speakers,
        "start_ms": min(item["start_ms"] for item in canonical),
        "end_ms": max(item["end_ms"] for item in canonical),
        "duration_ms": max(item["end_ms"] for item in canonical),
        "text_characters": sum(len(item["text"]) for item in nonempty),
    }
    return canonical, stats


def render_timeline(segments: list[dict[str, Any]]) -> str:
    lines = []
    for segment in segments:
        if not segment["text"]:
            continue
        lines.append(
            f"[{segment['segment_id']}]"
            f"[{format_ms(segment['start_ms'])}-{format_ms(segment['end_ms'])}]"
            f"[{segment['speaker_id']}] {segment['text']}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def prepare_transcript(
    source_json: str | pathlib.Path,
    canonical_json: str | pathlib.Path,
    timeline_path: str | pathlib.Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    rows = load_json(source_json)
    segments, stats = canonicalize_rows(rows)
    timeline = render_timeline(segments)
    atomic_write_json(canonical_json, segments)
    atomic_write_text(timeline_path, timeline)
    return segments, stats, timeline
