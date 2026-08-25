#!/usr/bin/env python3
"""CLI entry point for the RK1828 meeting Harness."""

from __future__ import annotations

import argparse
import json
import sys

from .pipeline import run_pipeline


DEFAULT_BOARD_SCRIPTS_DIR = "/userdata/meeting_agent/scripts"
DEFAULT_3DSPEAKER_DIR = "/userdata/3D-Speaker"
DEFAULT_3DSPEAKER_PYTHON = "/userdata/miniforge3/envs/3dspeaker/bin/python"
DEFAULT_ASR_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo"
DEFAULT_ASR_MODEL_DIR = "/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn"
DEFAULT_LLM_MODEL_DIR = "/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k"
DEFAULT_SERVER = "/usr/bin/rkllm3-server"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run source audio through diarization, Batch ASR, and an evidence-linked meeting summary."
    )
    parser.add_argument("--source-audio", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--trace-id", default=None)
    parser.add_argument("--meeting-id", default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--run-id", default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--overwrite", action="store_true")
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--board-scripts-dir", default=DEFAULT_BOARD_SCRIPTS_DIR)

    parser.add_argument("--3dspeaker-dir", default=DEFAULT_3DSPEAKER_DIR)
    parser.add_argument("--3dspeaker-python", default=DEFAULT_3DSPEAKER_PYTHON)
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--absorb-unknown-max", type=float, default=2.0)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)
    parser.add_argument("--trim-duration", type=float, default=0.0)

    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--encoder-core", default="0xff")
    parser.add_argument("--asr-llm-core", default="0xff")

    parser.add_argument("--model-dir", default=DEFAULT_LLM_MODEL_DIR)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18245)
    parser.add_argument("--ctx", type=int, default=16384)
    parser.add_argument("--predict", type=int, default=3072)
    parser.add_argument("--max-tokens", type=int, default=3072)
    parser.add_argument("--input-safety-tokens", type=int, default=512)
    parser.add_argument("--input-chars-per-token", type=float, default=1.3)
    parser.add_argument("--input-fixed-overhead-tokens", type=int, default=128)
    parser.add_argument("--chunk-overlap-segments", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--server-temp", type=float, default=0.0)
    parser.add_argument("--server-top-k", type=int, default=1)
    parser.add_argument("--server-top-p", type=float, default=1.0)
    parser.add_argument("--server-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=1200)
    parser.add_argument("--sample-interval", type=float, default=0.2)
    args = parser.parse_args(argv)

    if args.ctx <= 0 or args.predict <= 0 or args.max_tokens <= 0:
        parser.error("ctx, predict, and max-tokens must be positive")
    if args.predict < args.max_tokens:
        parser.error("predict must be greater than or equal to max-tokens")
    if args.input_safety_tokens < 0 or args.input_fixed_overhead_tokens < 0:
        parser.error("input token reserves must be non-negative")
    if args.input_chars_per_token <= 0:
        parser.error("input-chars-per-token must be positive")
    if args.chunk_overlap_segments < 0:
        parser.error("chunk-overlap-segments must be non-negative")
    if args.ctx <= args.max_tokens + args.input_safety_tokens:
        parser.error("ctx must exceed max-tokens plus input-safety-tokens")
    if args.ready_timeout <= 0 or args.request_timeout <= 0:
        parser.error("timeouts must be positive")
    if args.sample_interval <= 0:
        parser.error("sample-interval must be positive")
    for name in ("pad", "absorb_unknown_max", "max_known_segment", "max_unknown_segment", "trim_duration"):
        if getattr(args, name) < 0:
            parser.error(f"{name.replace('_', '-')} must be non-negative")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_pipeline(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "stage": "preflight", "error": repr(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
