#!/usr/bin/env python3
"""Inspect chapter core ranges and report overlaps in a Harness run."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any


TIMELINE_LINE_RE = re.compile(
    r"^\[(seg-\d+)\]\[(\d+m\d{2}s-\d+m\d{2}s)\]"
    r"\[[^\]]+\]\s+(.*)$"
)
REF_RE = re.compile(r"^(?:r|seg-?)(\d+)$")


def load_segments(root: pathlib.Path) -> dict[str, dict[str, str]]:
    timeline_path = root / "timeline.txt"
    segments: dict[str, dict[str, str]] = {}
    if not timeline_path.is_file():
        return segments

    for raw_line in timeline_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        match = TIMELINE_LINE_RE.match(raw_line.strip())
        if not match:
            continue
        segment_id, time_range, text = match.groups()
        number = int(segment_id.rsplit("-", 1)[1])
        info = {
            "segment_id": segment_id,
            "time": time_range,
            "text": text,
        }
        segments[f"r{number}"] = info
        segments[segment_id] = info
    return segments


def ref_number(ref: Any) -> int | None:
    match = REF_RE.fullmatch(str(ref).strip())
    return int(match.group(1)) if match else None


def chapter_range(chapter: dict[str, Any]) -> tuple[str, str]:
    start_ref = str(
        chapter.get("core_start_ref")
        or chapter.get("start_ref")
        or ""
    )
    end_ref = str(
        chapter.get("core_end_ref")
        or chapter.get("end_ref")
        or ""
    )
    return start_ref, end_ref


def print_segment(label: str, ref: str, segments: dict[str, dict[str, str]]) -> None:
    info = segments.get(ref)
    if info is None:
        print(f"  {label}: {ref}（未找到对应 Timeline segment）")
        return
    print(
        f"  {label}: {info['segment_id']} [{info['time']}] "
        f"{info['text']}"
    )


def inspect_run(root: pathlib.Path) -> int:
    segments = load_segments(root)
    files = sorted(
        root.glob("03_llm_summary/chapter_windows/window-*/final_json.txt")
    )
    if not files:
        print(f"没有找到章节窗口结果: {root / '03_llm_summary'}")
        return 1

    print(f"运行目录: {root}")
    print(f"章节窗口数: {len(files)}")

    for final_json_path in files:
        print()
        print("=" * 100)
        print(final_json_path.parent.name)
        print("=" * 100)

        try:
            data = json.loads(final_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"JSON 读取失败: {exc}")
            continue

        chapters = data.get("completed_chapters", [])
        if not isinstance(chapters, list):
            print("completed_chapters 不是数组")
            continue

        ordered = []
        for model_index, chapter in enumerate(chapters, 1):
            if not isinstance(chapter, dict):
                print(f"Chapter {model_index}: 不是对象")
                continue
            start_ref, end_ref = chapter_range(chapter)
            ordered.append(
                {
                    "model_index": model_index,
                    "chapter": chapter,
                    "start_ref": start_ref,
                    "end_ref": end_ref,
                    "start_number": ref_number(start_ref),
                    "end_number": ref_number(end_ref),
                }
            )

        ordered.sort(
            key=lambda item: (
                item["start_number"] if item["start_number"] is not None else 10**12,
                item["end_number"] if item["end_number"] is not None else 10**12,
                item["model_index"],
            )
        )

        previous: dict[str, Any] | None = None
        for sorted_index, item in enumerate(ordered, 1):
            chapter = item["chapter"]
            start_ref = item["start_ref"]
            end_ref = item["end_ref"]
            start_number = item["start_number"]
            end_number = item["end_number"]

            print()
            print(
                f"Chapter {sorted_index}（模型原序号 {item['model_index']}）: "
                f"{chapter.get('title')}"
            )
            print(f"  核心覆盖: {start_ref} - {end_ref}")
            print_segment("起点", start_ref, segments)
            print_segment("终点", end_ref, segments)
            print(f"  摘要: {chapter.get('summary')}")

            if (
                previous is not None
                and start_number is not None
                and previous["end_number"] is not None
                and start_number <= previous["end_number"]
            ):
                print()
                print("  !!! 检测到重叠 !!!")
                print(
                    f"  前一个章节: Chapter {previous['sorted_index']} "
                    f"{previous['start_ref']}-{previous['end_ref']}"
                )
                print(
                    f"  当前章节:   Chapter {sorted_index} "
                    f"{start_ref}-{end_ref}"
                )
                print(f"  重叠区间: {start_ref} - {previous['end_ref']}")

            previous = {
                "sorted_index": sorted_index,
                "start_ref": start_ref,
                "end_ref": end_ref,
                "end_number": end_number,
            }

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=pathlib.Path)
    args = parser.parse_args()
    return inspect_run(args.run_dir.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
