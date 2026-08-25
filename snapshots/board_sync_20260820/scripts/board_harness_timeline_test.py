#!/usr/bin/env python3
"""Run only the Meeting Harness LLM stage from a canonical Timeline text file."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from typing import Any


SCRIPT_PATH = pathlib.Path(__file__).resolve()
BOARD_SCRIPTS_ROOT = SCRIPT_PATH.parent
REPOSITORY_ROOT = SCRIPT_PATH.parents[2]
if (BOARD_SCRIPTS_ROOT / "harness").is_dir():
    # Board deployment uses /userdata/meeting_agent/scripts/harness.
    if str(BOARD_SCRIPTS_ROOT) not in sys.path:
        sys.path.insert(0, str(BOARD_SCRIPTS_ROOT))
    import harness as _deployed_harness

    # Source checkout is named meeting_harness; alias the deployed package so
    # the same test script works both locally and on the board.
    sys.modules.setdefault("meeting_harness", _deployed_harness)
elif str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


TIMELINE_LINE_RE = re.compile(
    r"^\[(seg-\d{6})\]"
    r"\[(\d+)m(\d{2})s-(\d+)m(\d{2})s\]"
    r"\[([^\]]+)\]\s+(.*)$"
)


def parse_time(minutes: str, seconds: str) -> int:
    return (int(minutes) * 60 + int(seconds)) * 1000


def parse_timeline(path: pathlib.Path) -> tuple[list[dict[str, Any]], list[str]]:
    segments = []
    speaker_ids = set()
    previous_index = 0
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line:
            continue
        match = TIMELINE_LINE_RE.match(line)
        if not match:
            raise ValueError(f"invalid Timeline line {line_number}: {raw_line[:160]!r}")
        segment_id, start_m, start_s, end_m, end_s, speaker_id, text = match.groups()
        index = int(segment_id.rsplit("-", 1)[1])
        start_ms = parse_time(start_m, start_s)
        end_ms = parse_time(end_m, end_s)
        if index <= previous_index:
            raise ValueError(f"segment IDs are not increasing at line {line_number}")
        if end_ms <= start_ms:
            raise ValueError(f"segment has invalid time range at line {line_number}")
        if not text.strip():
            raise ValueError(f"segment has empty text at line {line_number}")
        segments.append(
            {
                "segment_id": segment_id,
                "index": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "speaker_id": speaker_id,
                "text": text.strip(),
                "status": "ok",
            }
        )
        speaker_ids.add(speaker_id)
        previous_index = index
    if not segments:
        raise ValueError(f"Timeline is empty: {path}")
    return segments, sorted(speaker_ids)


def config_from_args(args: argparse.Namespace):
    from meeting_harness.llm import LlmConfig
    from meeting_harness.product_summary import ProductSummaryConfig

    llm = LlmConfig(
        board_scripts_dir=pathlib.Path(args.board_scripts_dir),
        model_dir=pathlib.Path(args.model_dir),
        server=pathlib.Path(args.server),
        host=args.host,
        port=args.port,
        ctx=args.ctx,
        predict=args.predict,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        server_temp=args.server_temp,
        server_top_k=args.server_top_k,
        server_top_p=args.server_top_p,
        server_repeat_penalty=args.server_repeat_penalty,
        ready_timeout=args.ready_timeout,
        request_timeout=args.request_timeout,
    )
    return ProductSummaryConfig(
        llm=llm,
        safety_tokens=args.input_safety_tokens,
        chars_per_token=args.input_chars_per_token,
        fixed_overhead_tokens=args.input_fixed_overhead_tokens,
        resume=args.resume,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--out-dir", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--overwrite", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--board-scripts-dir", default="/userdata/meeting_agent/scripts")
    parser.add_argument(
        "--model-dir",
        default="/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k",
    )
    parser.add_argument("--server", default="/usr/bin/rkllm3-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18245)
    parser.add_argument("--ctx", type=int, default=16384)
    parser.add_argument("--predict", type=int, default=3072)
    parser.add_argument("--max-tokens", type=int, default=3072)
    parser.add_argument("--input-safety-tokens", type=int, default=512)
    parser.add_argument("--input-chars-per-token", type=float, default=1.3)
    parser.add_argument("--input-fixed-overhead-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--server-temp", type=float, default=0.0)
    parser.add_argument("--server-top-k", type=int, default=1)
    parser.add_argument("--server-top-p", type=float, default=1.0)
    parser.add_argument("--server-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=1200)
    args = parser.parse_args()
    if args.ctx <= args.max_tokens + args.input_safety_tokens:
        parser.error("ctx must exceed max-tokens plus input-safety-tokens")
    if args.predict < args.max_tokens:
        parser.error("predict must be greater than or equal to max-tokens")
    if args.input_chars_per_token <= 0:
        parser.error("input-chars-per-token must be positive")
    return args


def load_memory_helper(board_scripts_dir: pathlib.Path):
    import importlib.util

    helper_path = board_scripts_dir / "board_meeting_chain_profile.py"
    spec = importlib.util.spec_from_file_location(
        "meeting_harness_timeline_memory_helper", helper_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load board helper: {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    args = parse_args()
    timeline_path = pathlib.Path(args.timeline).expanduser().resolve()
    out_dir = pathlib.Path(args.out_dir).expanduser().resolve()
    if not timeline_path.is_file():
        raise FileNotFoundError(f"Timeline not found: {timeline_path}")
    if out_dir.exists() and any(out_dir.iterdir()):
        if not args.overwrite and not args.resume:
            raise FileExistsError(f"out-dir is not empty: {out_dir}; use --overwrite or --resume")
    if args.overwrite and out_dir.exists():
        import shutil

        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from meeting_harness.artifacts import atomic_write_json, atomic_write_text
    from meeting_harness.display import build_frontend_result, render_meeting_display
    from meeting_harness.product_summary import run_product_summary_stage
    from meeting_harness.transcript import render_timeline

    started = time.time()
    segments, speaker_ids = parse_timeline(timeline_path)
    canonical_timeline = render_timeline(segments)
    atomic_write_text(out_dir / "timeline.txt", canonical_timeline)
    atomic_write_json(
        out_dir / "timeline_input.json",
        {
            "source": str(timeline_path),
            "segment_count": len(segments),
            "speaker_ids": speaker_ids,
            "duration_ms": segments[-1]["end_ms"],
        },
    )
    config = config_from_args(args)
    llm_dir = out_dir / "03_llm_summary"
    memory_helper = load_memory_helper(pathlib.Path(args.board_scripts_dir))
    memory_sampler = memory_helper.MemorySampler(
        out_dir / "runtime" / "memory_samples.jsonl", interval_s=0.2
    )
    memory_sampler.start()
    run = run_product_summary_stage(
        config=config,
        segments=segments,
        speaker_ids=speaker_ids,
        timeline=canonical_timeline,
        out_dir=llm_dir,
        sampler=memory_sampler,
    )
    memory_sampler.stop()
    atomic_write_json(out_dir / "runtime" / "memory_summary.json", memory_sampler.summary())
    summary = run["summary"]
    meeting = {
        "meeting_id": f"mock_{timeline_path.stem}",
        "duration_ms": segments[-1]["end_ms"],
        "source_audio": None,
    }
    frontend = build_frontend_result(
        meeting,
        segments,
        summary,
        context_policy=run["policy"],
    )
    atomic_write_json(out_dir / "meeting_summary.json", summary)
    atomic_write_json(out_dir / "meeting_frontend.json", frontend)
    atomic_write_text(out_dir / "meeting_display.txt", render_meeting_display(frontend))
    atomic_write_json(
        out_dir / "timeline_test_result.json",
        {
            "status": "ok",
            "source_timeline": str(timeline_path),
            "segment_count": len(segments),
            "speaker_ids": speaker_ids,
            "elapsed_seconds": round(time.time() - started, 3),
            "summary_run": run,
        },
    )
    print(json.dumps({
        "status": "ok",
        "policy": run["policy"],
        "segment_count": len(segments),
        "request_count": run["request_count"],
        "validated_request_count": run["validated_request_count"],
        "elapsed_seconds": round(time.time() - started, 3),
        "out_dir": str(out_dir),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": repr(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise
