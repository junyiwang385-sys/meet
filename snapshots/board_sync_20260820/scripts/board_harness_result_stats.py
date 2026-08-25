#!/usr/bin/env python3
"""Print timing, output-size, token, and memory statistics for a Harness run."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


def load_json(path: pathlib.Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def text_chars(path: pathlib.Path) -> int | None:
    if not path.is_file():
        return None
    return len(path.read_text(encoding="utf-8", errors="replace"))


def format_seconds(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "无"
    minutes, seconds = divmod(float(value), 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:05.2f}s ({value}s)"
    if minutes:
        return f"{minutes}m{seconds:05.2f}s ({value}s)"
    return f"{seconds:.3f}s"


def discover_request_dirs(llm_dir: pathlib.Path) -> list[pathlib.Path]:
    candidates = []
    for status_path in llm_dir.rglob("status.json"):
        request_dir = status_path.parent
        if (request_dir / "final_json.txt").is_file():
            candidates.append(request_dir)
    return sorted(candidates, key=lambda path: str(path.relative_to(llm_dir)))


def print_memory(root: pathlib.Path) -> None:
    path = root / "runtime" / "memory_summary.json"
    print("\n========== 内存统计 ==========")
    if not path.is_file():
        print("未找到 runtime/memory_summary.json")
        return
    memory = load_json(path)
    print("采样数:", memory.get("samples"))
    print("基线整板占用 MB:", memory.get("baseline_board_used_mb"))
    print("整板峰值 MB:", memory.get("board_used_peak_mb"))
    print("相对基线峰值增量 MB:", memory.get("board_used_peak_delta_mb"))
    print("最低 MemAvailable MB:", memory.get("mem_available_min_mb"))
    print("\n各阶段整板峰值 MB:")
    for phase, value in memory.get("phase_board_used_peak_mb", {}).items():
        print(f"  {phase}: {value}")
    print("\n进程峰值 MB:")
    for name, values in memory.get("process_peaks", {}).items():
        print(
            f"  {name}: rss={values.get('rss_peak_mb')}, "
            f"hwm={values.get('hwm_peak_mb')}, vmsize={values.get('vmsize_peak_mb')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=pathlib.Path, help="Harness output directory")
    args = parser.parse_args()
    root = args.run_dir.expanduser().resolve()
    result_path = root / "meeting_result.json"
    if not result_path.is_file():
        parser.error(f"meeting_result.json not found: {result_path}")

    result = load_json(result_path)
    runtime = result.get("runtime", {})
    print("========== 运行概况 ==========")
    print("目录:", root)
    print("状态:", result.get("status"))
    print("上下文策略:", runtime.get("context_policy"))
    print("开始时间:", runtime.get("started_at"))
    print("结束时间:", runtime.get("finished_at"))
    print("总耗时:", format_seconds(runtime.get("total_elapsed_seconds")))
    print("错误:", result.get("errors", []))

    print("\n========== Pipeline 各阶段耗时 ==========")
    stages = runtime.get("stages", {})
    if not stages:
        print("无阶段记录")
    for name, stage in stages.items():
        print(
            f"{name}: status={stage.get('status')}, "
            f"elapsed={format_seconds(stage.get('elapsed_seconds'))}"
        )

    llm_dir = root / "03_llm_summary"
    request_dirs = discover_request_dirs(llm_dir)
    total_raw = 0
    total_thinking = 0
    total_final = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    print("\n========== LLM 请求与输出 ==========")
    if not request_dirs:
        print("未找到 LLM 请求结果")
    for request_dir in request_dirs:
        status = load_json(request_dir / "status.json")
        usage = status.get("usage") if isinstance(status.get("usage"), dict) else {}
        raw_chars = text_chars(request_dir / "raw_content.txt")
        thinking_chars = text_chars(request_dir / "thinking.txt")
        final_chars = text_chars(request_dir / "final_json.txt")
        total_raw += raw_chars or 0
        total_thinking += thinking_chars or 0
        total_final += final_chars or 0
        total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
        total_completion_tokens += int(usage.get("completion_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        name = str(request_dir.relative_to(llm_dir))
        print(f"\n{name}")
        print("  request_id:", status.get("request_id"))
        print("  请求耗时:", format_seconds(status.get("request_elapsed_seconds")))
        print("  finish_reason:", status.get("finish_reason"))
        print("  context_truncated:", status.get("context_truncated"))
        print("  usage:", usage)
        print("  原始模型输出字符:", raw_chars)
        print("  thinking 字符:", thinking_chars)
        print("  最终 JSON 字符:", final_chars)

    print("\n---------- LLM 合计 ----------")
    print("请求数:", len(request_dirs))
    print("原始模型输出总字符（含 think 标签时以 raw_content 为准）:", total_raw)
    print("分离后 thinking 总字符:", total_thinking)
    print("最终 JSON 总字符:", total_final)
    print("thinking + 最终 JSON 总字符:", total_thinking + total_final)
    print("prompt_tokens 合计:", total_prompt_tokens)
    print("completion_tokens 合计:", total_completion_tokens)
    print("total_tokens 合计:", total_tokens)

    print("\n========== 最终产物字符数 ==========")
    for name in (
        "timeline.txt",
        "meeting_summary.json",
        "meeting_frontend.json",
        "meeting_display.txt",
        "meeting_result.json",
    ):
        print(f"{name}:", text_chars(root / name))

    print_memory(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
