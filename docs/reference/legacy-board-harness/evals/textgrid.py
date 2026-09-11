"""Parse Praat TextGrid speaker tiers into canonical evaluation segments."""

from __future__ import annotations

import pathlib
import re
from typing import Any

_INTERVAL_RE = re.compile(
    r"intervals \[\d+\]:\s*(.*?)(?=\n\s*intervals \[\d+\]:|\Z)",
    re.DOTALL,
)
_ITEM_RE = re.compile(r"item \[\d+\]:\s*(.*?)(?=\n\s*item \[\d+\]:|\Z)", re.DOTALL)


def _number(block: str, field: str) -> float | None:
    match = re.search(rf"\b{field}\s*=\s*([0-9]+(?:\.[0-9]+)?)", block)
    return float(match.group(1)) if match else None


def _quoted(block: str, field: str) -> str | None:
    match = re.search(rf'\b{field}\s*=\s*"((?:[^"]|"")*)"', block)
    return match.group(1).replace('""', '"') if match else None


def parse_textgrid(path: str | pathlib.Path) -> tuple[list[dict[str, Any]], list[str]]:
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for item in _ITEM_RE.findall(text):
        speaker = _quoted(item, "name") or "unknown"
        for interval in _INTERVAL_RE.findall(item):
            start = _number(interval, "xmin")
            end = _number(interval, "xmax")
            value = (_quoted(interval, "text") or "").strip()
            if start is None or end is None or end <= start:
                continue
            rows.append(
                {
                    "start_ms": round(start * 1000),
                    "end_ms": round(end * 1000),
                    "speaker_id": speaker,
                    "text": value,
                    "status": "ok" if value else "transcript_empty",
                }
            )
    rows.sort(key=lambda item: (item["start_ms"], item["end_ms"], item["speaker_id"]))
    segments: list[dict[str, Any]] = []
    for index, row in enumerate((item for item in rows if item["text"]), 1):
        segments.append(
            {
                **row,
                "segment_id": f"seg-{index:06d}",
                "index": index,
            }
        )
    speakers = sorted({str(item["speaker_id"]) for item in rows})
    return segments, speakers


def render_reference_timeline(segments: list[dict[str, Any]]) -> str:
    def format_ms(value: int) -> str:
        total_seconds = round(value / 1000)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}m{seconds:02d}s"

    return "".join(
        f"[{item['segment_id']}][{format_ms(item['start_ms'])}-{format_ms(item['end_ms'])}]"
        f"[{item['speaker_id']}] {item['text']}\n"
        for item in segments
    )
