#!/usr/bin/env python3
"""Report per-request token usage and Timeline segment coverage."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any


SEGMENT_RE = re.compile(r"\[(seg-\d{6})\]")
REF_RE = re.compile(r"seg-\d{6}")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def refs_from_text(text: str) -> list[str]:
    return list(dict.fromkeys(REF_RE.findall(text)))


def request_usage(status_path: pathlib.Path) -> tuple[int, int, int]:
    status = read_json(status_path)
    usage = status.get("usage") or {}
    return (
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        int(usage.get("total_tokens") or 0),
    )


def chapter_coverage(window_dir: pathlib.Path, refs: list[str]) -> tuple[list[str], dict[str, Any]]:
    """Return refs covered by validated chapter ranges and the uncovered groups."""
    payload = None
    for name in ("validated_window.json", "final_json.txt"):
        path = window_dir / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, json.JSONDecodeError):
            continue
    chapters = []
    if isinstance(payload, dict):
        chapters = payload.get("completed_chapters") or payload.get("chapters") or []
    positions = {ref: index for index, ref in enumerate(refs)}
    covered_positions: set[int] = set()
    ranges = []
    chapter_details = []
    if isinstance(chapters, list):
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            start = chapter.get("start_ref")
            end = chapter.get("end_ref")
            if start not in positions or end not in positions:
                continue
            start_pos = positions[start]
            end_pos = positions[end]
            if end_pos < start_pos:
                continue
            covered_positions.update(range(start_pos, end_pos + 1))
            ranges.append((start_pos, end_pos))
            chapter_details.append({
                "title": chapter.get("title"),
                "core_start_ref": chapter.get("core_start_ref", start),
                "core_end_ref": chapter.get("core_end_ref", end),
                "start_ref": start,
                "end_ref": end,
            })
    uncovered = [ref for index, ref in enumerate(refs) if index not in covered_positions]
    if uncovered:
        first_uncovered = min(index for index in range(len(refs)) if index not in covered_positions)
        last_covered = max(covered_positions) if covered_positions else -1
        tail_start = max(last_covered + 1, first_uncovered)
        tail = [ref for index, ref in enumerate(refs) if index >= tail_start and index not in covered_positions]
        middle = [ref for index, ref in enumerate(refs) if index not in covered_positions and index < tail_start]
    else:
        middle = []
        tail = []
    return uncovered, {
        "chapter_ranges": ranges,
        "chapter_details": chapter_details,
        "chapter_covered_refs": [ref for index, ref in enumerate(refs) if index in covered_positions],
        "uncovered_refs": uncovered,
        "uncovered_middle_refs": middle,
        "uncovered_tail_refs": tail,
    }


def print_request(
    label: str,
    status_path: pathlib.Path,
    refs: list[str],
    *,
    estimated_prompt_tokens: Any = None,
) -> tuple[int, int, int]:
    status = read_json(status_path)
    prompt_tokens, completion_tokens, total_tokens = request_usage(status_path)
    print(f"\n[{label}]")
    print("request_id:", status.get("request_id"))
    print("finish_reason:", status.get("finish_reason"))
    print("context_truncated:", status.get("context_truncated"))
    print("prompt_tokens:", prompt_tokens)
    print("completion_tokens:", completion_tokens)
    print("total_tokens:", total_tokens)
    print("estimated_prompt_tokens:", estimated_prompt_tokens)
    print("request_elapsed_seconds:", status.get("request_elapsed_seconds"))
    print("input_refs_count:", len(refs))
    if refs:
        print("input_refs_first:", refs[0])
        print("input_refs_last:", refs[-1])
        print("input_refs:", ", ".join(refs))
    else:
        print("input_refs: none")
    return prompt_tokens, completion_tokens, total_tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=pathlib.Path)
    args = parser.parse_args()
    root = args.run_dir.expanduser().resolve()
    llm_dir = root / "03_llm_summary"
    if not llm_dir.is_dir():
        parser.error(f"missing 03_llm_summary: {llm_dir}")

    plan_path = llm_dir / "plan.json"
    plan = read_json(plan_path) if plan_path.is_file() else {}
    plan_windows = {
        item.get("window_id"): item
        for item in plan.get("windows", [])
        if isinstance(item, dict)
    }

    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    request_count = 0

    print("========== Harness Window Token Stats ==========")
    print("run_dir:", root)
    print("policy:", plan.get("policy"))
    print("window_count:", plan.get("window_count"))

    window_root = llm_dir / "chapter_windows"
    for window_dir in sorted(window_root.glob("window-*")):
        status_path = window_dir / "status.json"
        timeline_path = window_dir / "timeline.txt"
        if not status_path.is_file():
            continue
        timeline = timeline_path.read_text(encoding="utf-8", errors="replace") if timeline_path.is_file() else ""
        refs = list(dict.fromkeys(SEGMENT_RE.findall(timeline)))
        window_id = window_dir.name
        record = plan_windows.get(window_id, {})
        values = print_request(
            window_id,
            status_path,
            refs,
            estimated_prompt_tokens=record.get("estimated_prompt_tokens"),
        )
        total_prompt += values[0]
        total_completion += values[1]
        total_tokens += values[2]
        request_count += 1
        input_start_ref = record.get("input_start_ref", record.get("start_ref"))
        input_end_ref = record.get("input_end_ref", record.get("end_ref"))
        carryover_start_ref = record.get("carryover_start_ref", record.get("next_start_ref"))
        completed_end_ref = record.get("completed_end_ref")
        if completed_end_ref is None and carryover_start_ref in refs:
            completed_index = refs.index(carryover_start_ref) - 1
            completed_end_ref = refs[completed_index] if completed_index >= 0 else None
        if completed_end_ref is None and refs and carryover_start_ref is None:
            completed_end_ref = refs[-1]
        completed_count = record.get("completed_segment_count")
        carryover_count = record.get("carryover_segment_count")
        if carryover_start_ref in refs:
            carryover_index = refs.index(carryover_start_ref)
            completed_count = carryover_index
            carryover_count = len(refs) - carryover_index
        elif carryover_start_ref is None:
            completed_count = len(refs)
            carryover_count = 0
        print("input_start_ref:", input_start_ref)
        print("input_end_ref:", input_end_ref)
        print("completed_end_ref:", completed_end_ref)
        print("carryover_start_ref:", carryover_start_ref)
        print("input_segment_count:", record.get("input_segment_count", len(refs)))
        print("completed_segment_count:", completed_count)
        print("carryover_segment_count:", carryover_count)
        print("completed_chapter_count:", record.get("completed_chapter_count"))
        print("action_candidate_count:", record.get("action_candidate_count"))
        _, coverage = chapter_coverage(window_dir, refs)
        uncovered_set = set(coverage["uncovered_refs"])
        if carryover_start_ref in refs:
            carryover_index = refs.index(carryover_start_ref)
            uncovered_before_carryover = [
                ref for index, ref in enumerate(refs)
                if index < carryover_index and ref in uncovered_set
            ]
            carryover_context_refs = [
                ref for index, ref in enumerate(refs)
                if index >= carryover_index and ref in uncovered_set
            ]
        else:
            uncovered_before_carryover = list(coverage["uncovered_refs"])
            carryover_context_refs = []
        for chapter_index, chapter in enumerate(coverage["chapter_details"], 1):
            print(
                f"chapter_{chapter_index}_range:",
                f"core={chapter['core_start_ref']}..{chapter['core_end_ref']}",
                f"full={chapter['start_ref']}..{chapter['end_ref']}",
                f"title={chapter['title']}",
            )
        print("chapter_covered_segment_count_actual:", len(coverage["chapter_covered_refs"]))
        print("uncovered_segment_count_actual:", len(coverage["uncovered_refs"]))
        print("uncovered_before_carryover_refs:", ", ".join(uncovered_before_carryover) or "none")
        print("carryover_context_uncovered_refs:", ", ".join(carryover_context_refs) or "none")
        print("uncovered_middle_refs:", ", ".join(coverage["uncovered_middle_refs"]) or "none")
        print("uncovered_tail_refs:", ", ".join(coverage["uncovered_tail_refs"]) or "none")
        print("uncovered_refs:", ", ".join(coverage["uncovered_refs"]) or "none")

    for name, label in (
        ("full", "full-summary-short-path"),
        ("full_summary", "full-summary-from-chapters"),
        ("action_review", "action-review"),
    ):
        request_dir = llm_dir / "requests" / name
        status_path = request_dir / "status.json"
        messages_path = request_dir / "messages.json"
        if not status_path.is_file():
            continue
        refs = []
        chapter_ids = []
        if messages_path.is_file():
            message_text = messages_path.read_text(encoding="utf-8", errors="replace")
            if name == "full_summary":
                actual = message_text.split("章节速览：\\n", 1)[-1]
                refs = refs_from_text(actual)
                chapter_ids = list(dict.fromkeys(re.findall(r'"id"\\s*:\\s*(\\d+)', actual)))
            elif name == "action_review":
                candidate_part = message_text.split("候选：\\n", 1)[-1]
                candidate_part = candidate_part.split("\\n\\n证据：\\n", 1)[0]
                evidence_part = message_text.split("证据：\\n", 1)[-1]
                refs = list(dict.fromkeys(refs_from_text(candidate_part + evidence_part)))
            else:
                refs = refs_from_text(message_text)
        values = print_request(label, status_path, refs)
        if chapter_ids:
            print("input_chapter_ids:", ", ".join(chapter_ids))
        if name == "full_summary":
            print("input_type: validated chapter summaries plus evidence refs (not raw Timeline)")
        total_prompt += values[0]
        total_completion += values[1]
        total_tokens += values[2]
        request_count += 1

    print("\n========== Totals ==========")
    print("persisted_request_count:", request_count)
    print("prompt_tokens_total:", total_prompt)
    print("completion_tokens_total:", total_completion)
    print("total_tokens_total:", total_tokens)
    print("max_prompt_tokens:", max(
        [request_usage(path)[0] for path in llm_dir.glob("chapter_windows/*/status.json")]
        + [request_usage(path)[0] for path in (
            llm_dir / "requests" / "full" / "status.json",
            llm_dir / "requests" / "full_summary" / "status.json",
            llm_dir / "requests" / "action_review" / "status.json",
        ) if path.is_file()]
        or [0]
    ))
    print("\n说明：input_refs 是该请求 Prompt 中实际出现的 segment_id 去重列表。")
    print("章节窗口的 refs 来自该窗口 timeline.txt；全文摘要和待办请求的 refs 来自 messages.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
