#!/usr/bin/env python3
"""Evaluate Qwen3-ASR by feeding the original audio file directly.

This is the baseline for long meeting audio: no channel remixing and no format
conversion. It records whether the board ASR demo can directly consume the
original FLAC and whether the transcript length/RTF looks complete.
"""

import argparse
import pathlib
import time

from board_asr_eval_common import (
    DEFAULT_ASR_DIR,
    DEFAULT_ASR_MODEL_DIR,
    DEFAULT_AUDIO,
    DEFAULT_TEXTGRID,
    MemorySampler,
    completeness_flags,
    distance_metrics,
    extract_textgrid_reference,
    log,
    prepare_out_dir,
    preview_text,
    run_asr_once,
    soxi_info,
    write_json,
)


DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/asr_eval/L_R004S06C01_direct_flac"


def parse_args():
    parser = argparse.ArgumentParser(description="Direct original-audio Qwen3-ASR evaluation with optional TextGrid comparison.")
    parser.add_argument("--audio", default=DEFAULT_AUDIO, help="Original audio file, usually the source FLAC")
    parser.add_argument("--reference-textgrid", default=DEFAULT_TEXTGRID, help="Reference TextGrid path; set empty string to skip")
    parser.add_argument("--reference-tier", help="Optional TextGrid tier name, e.g. 001-M; defaults to all non-empty tiers")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--asr-mode", choices=["offline", "online", "online-stream"], default="offline")
    parser.add_argument("--asr-transcript-regex")
    parser.add_argument("--sample-interval", type=float, default=0.5)
    return parser.parse_args()


def main():
    args = parse_args()
    out_dir = prepare_out_dir(args.out_dir, args.overwrite)
    log("[ASR-DIRECT] start original audio direct evaluation")
    log(f"[ASR-DIRECT] audio={args.audio}")
    log(f"[ASR-DIRECT] out_dir={out_dir}")
    write_json(out_dir / "run_config.json", vars(args))

    audio_info = soxi_info(args.audio)
    write_json(out_dir / "audio_info.json", audio_info)
    log(f"[AUDIO] channels={audio_info.get('channels')}, sample_rate={audio_info.get('sample_rate')}, duration={audio_info.get('duration_seconds')}s")

    reference = ""
    reference_meta = {}
    if args.reference_textgrid:
        reference, reference_meta = extract_textgrid_reference(args.reference_textgrid, args.reference_tier)
        (out_dir / "reference_text.txt").write_text(reference, encoding="utf-8")
        write_json(out_dir / "reference_meta.json", reference_meta)
        log(f"[REF] chars={len(reference)}, intervals={reference_meta.get('interval_count')}, tier={args.reference_tier or 'ALL'}")

    sampler = MemorySampler(out_dir / "memory_samples.jsonl", interval_s=args.sample_interval)
    sampler.start()
    started = time.time()
    try:
        sampler.set_phase("asr_direct")
        result = run_asr_once(
            args.asr_dir,
            args.asr_model_dir,
            args.audio,
            out_dir / "asr_raw.log",
            sampler=sampler,
            target_name="asr_direct",
            asr_mode=args.asr_mode,
            regex=args.asr_transcript_regex,
        )
    finally:
        sampler.stop()
    total_elapsed = round(time.time() - started, 3)
    memory = sampler.summary()
    write_json(out_dir / "memory_summary.json", memory)

    transcript = result["transcript"]
    (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    write_json(out_dir / "asr_cmd.json", result["cmd"])

    audio_duration = audio_info.get("duration_seconds")
    flags = completeness_flags(audio_duration, result["elapsed_seconds"], len(transcript), len(reference))
    metrics = distance_metrics(transcript, reference) if reference else {}
    report = {
        "status": "ok" if result["return_code"] == 0 and transcript else "asr_failed_or_empty",
        "mode": "direct-original-audio",
        "audio": args.audio,
        "audio_info": audio_info,
        "reference_textgrid": args.reference_textgrid,
        "reference_tier": args.reference_tier,
        "reference_meta": reference_meta,
        "asr_return_code": result["return_code"],
        "asr_elapsed_seconds": result["elapsed_seconds"],
        "wall_elapsed_seconds": total_elapsed,
        "asr_extract_method": result["extract_method"],
        "transcript_chars": len(transcript),
        "reference_chars": len(reference),
        "completeness": flags,
        "metrics": metrics,
        "memory": memory,
        "outputs": {
            "audio_info": str(out_dir / "audio_info.json"),
            "asr_raw_log": str(out_dir / "asr_raw.log"),
            "transcript": str(out_dir / "transcript.txt"),
            "reference_text": str(out_dir / "reference_text.txt"),
            "asr_eval": str(out_dir / "asr_eval.json"),
            "memory_summary": str(out_dir / "memory_summary.json"),
            "memory_samples": str(out_dir / "memory_samples.jsonl"),
        },
    }
    write_json(out_dir / "asr_eval.json", report)
    log(f"[ASR-DIRECT] done status={report['status']}, elapsed={result['elapsed_seconds']}s, rtf={flags.get('rtf')}")
    log(f"[ASR-DIRECT] transcript_chars={len(transcript)}, reference_chars={len(reference)}, suspicious={flags.get('suspicious')}")
    if transcript:
        log(f"[ASR-DIRECT] transcript_preview={preview_text(transcript)}")
    log(f"[OUTPUT] asr_eval={out_dir / 'asr_eval.json'}")
    log(f"[OUTPUT] transcript={out_dir / 'transcript.txt'}")
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
