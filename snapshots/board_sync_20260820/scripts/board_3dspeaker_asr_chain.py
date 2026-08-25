#!/usr/bin/env python3
"""Run board-side 3D-Speaker segmentation plus batch Qwen3-ASR.

This wraps two board scripts:
1. board_3dspeaker_segment_prepare.py
2. board_segment_asr_batch.py

Input source audio can be the original FLAC. Output includes cut WAV segments,
segment_transcripts.json, and llm_input_timeline.txt.
"""

import argparse
import json
import pathlib
import subprocess
import sys
import time


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def run_step(cmd, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    log("running: " + " ".join(str(x) for x in cmd))
    with log_path.open("wb") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    elapsed = round(time.time() - started, 3)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    return {"cmd": [str(x) for x in cmd], "return_code": proc.returncode, "elapsed_seconds": elapsed, "log": str(log_path), "output_tail": tail}


def main():
    parser = argparse.ArgumentParser(description="Board 3D-Speaker -> cut WAV -> batch Qwen3-ASR chain.")
    parser.add_argument("--source-audio", required=True, help="Original FLAC/WAV input")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--3dspeaker-dir", default="/userdata/3D-Speaker")
    parser.add_argument("--asr-dir", default="/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo")
    parser.add_argument("--asr-model-dir", default="/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn")
    parser.add_argument("--asr-mode", choices=["offline", "online", "online-stream"], default="offline")
    parser.add_argument("--trim-duration", type=float, default=0.0, help="Smoke test with first N seconds only; 0 means full audio")
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--known-merge-gap", type=float, default=0.5)
    parser.add_argument("--unknown-min-gap", type=float, default=0.5)
    parser.add_argument("--unknown-merge-gap", type=float, default=0.5)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)
    parser.add_argument("--asr-limit", type=int, default=0, help="Only ASR first N segments; 0 means all")
    parser.add_argument("--asr-timeout", type=float, default=0.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"out-dir exists and is not empty: {out_dir}; use --overwrite")
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "chain_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    segment_out = out_dir / "01_3dspeaker_segments"
    asr_out = out_dir / "02_segment_asr"

    prepare_script = SCRIPT_DIR / "board_3dspeaker_segment_prepare.py"
    asr_script = SCRIPT_DIR / "board_segment_asr_batch.py"

    prepare_cmd = [
        sys.executable, str(prepare_script),
        "--source-audio", args.source_audio,
        "--out-dir", str(segment_out),
        "--3dspeaker-dir", args.__dict__["3dspeaker_dir"],
        "--python", sys.executable,
        "--pad", str(args.pad),
        "--known-merge-gap", str(args.known_merge_gap),
        "--unknown-min-gap", str(args.unknown_min_gap),
        "--unknown-merge-gap", str(args.unknown_merge_gap),
        "--max-known-segment", str(args.max_known_segment),
        "--max-unknown-segment", str(args.max_unknown_segment),
        "--overwrite",
    ]
    if args.trim_duration > 0:
        prepare_cmd.extend(["--trim-duration", str(args.trim_duration)])

    prepare_report = run_step(prepare_cmd, logs_dir / "01_3dspeaker_segments.log")
    if prepare_report["return_code"] != 0:
        summary = {"success": False, "failed_step": "3dspeaker_segments", "prepare_report": prepare_report}
        (out_dir / "board_3dspeaker_asr_chain_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        sys.exit(2)

    segment_summary_path = segment_out / "board_3dspeaker_segment_summary.json"
    segment_summary = json.loads(segment_summary_path.read_text(encoding="utf-8"))
    wav_dir = segment_summary["wav_segments_dir"]
    manifest = segment_summary["cut_segments_csv"]

    asr_cmd = [
        sys.executable, str(asr_script),
        "--wav-dir", wav_dir,
        "--manifest", manifest,
        "--out-dir", str(asr_out),
        "--asr-dir", args.asr_dir,
        "--asr-model-dir", args.asr_model_dir,
        "--asr-mode", args.asr_mode,
        "--overwrite",
    ]
    if args.asr_limit > 0:
        asr_cmd.extend(["--limit", str(args.asr_limit)])
    if args.asr_timeout > 0:
        asr_cmd.extend(["--timeout", str(args.asr_timeout)])

    asr_report = run_step(asr_cmd, logs_dir / "02_segment_asr.log")
    if asr_report["return_code"] != 0:
        summary = {
            "success": False,
            "failed_step": "segment_asr",
            "segment_summary": segment_summary,
            "prepare_report": prepare_report,
            "asr_report": asr_report,
        }
        (out_dir / "board_3dspeaker_asr_chain_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        sys.exit(3)

    asr_summary_path = asr_out / "batch_asr_summary.json"
    asr_summary = json.loads(asr_summary_path.read_text(encoding="utf-8"))
    summary = {
        "success": True,
        "source_audio": args.source_audio,
        "out_dir": str(out_dir),
        "segment_summary_path": str(segment_summary_path),
        "asr_summary_path": str(asr_summary_path),
        "segment_transcripts_json": str(asr_out / "segment_transcripts.json"),
        "llm_input_timeline": str(asr_out / "llm_input_timeline.txt"),
        "wav_segments_dir": wav_dir,
        "cut_segments_csv": manifest,
        "segment_summary": segment_summary,
        "asr_summary": asr_summary,
        "prepare_report": prepare_report,
        "asr_report": asr_report,
    }
    (out_dir / "board_3dspeaker_asr_chain_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote chain outputs to: {out_dir}")
    print(f"- {out_dir / 'board_3dspeaker_asr_chain_summary.json'}")
    print(f"- {asr_out / 'segment_transcripts.json'}")
    print(f"- {asr_out / 'llm_input_timeline.txt'}")


if __name__ == "__main__":
    main()
