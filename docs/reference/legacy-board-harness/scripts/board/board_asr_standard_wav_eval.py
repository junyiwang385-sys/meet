#!/usr/bin/env python3
"""Evaluate Qwen3-ASR after converting long meeting audio to standard mono WAV.

The target ASR input format is full-coverage 16 kHz, mono, 16-bit PCM WAV.
By default this script processes the full audio in chunks and concatenates all
chunk transcripts; chunking is complete coverage, not truncation.
"""

import argparse
import json
import math
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
    run_capture,
    soxi_info,
    write_json,
)


DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/asr_eval/L_R004S06C01_standard_wav_chunk120"


def parse_args():
    parser = argparse.ArgumentParser(description="Standard mono-WAV long-audio Qwen3-ASR evaluation with optional chunking and TextGrid comparison.")
    parser.add_argument("--audio", default=DEFAULT_AUDIO, help="Source audio file, e.g. original 8ch FLAC")
    parser.add_argument("--reference-textgrid", default=DEFAULT_TEXTGRID, help="Reference TextGrid path; set empty string to skip")
    parser.add_argument("--reference-tier", help="Optional TextGrid tier name, e.g. 001-M; defaults to all non-empty tiers")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--asr-mode", choices=["offline", "online", "online-stream"], default="offline")
    parser.add_argument("--asr-transcript-regex")
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--chunk-seconds", type=float, default=120.0, help="Chunk length for full-coverage ASR; use 0 to run one full converted WAV")
    parser.add_argument("--source-mode", choices=["mono-mix", "channel"], default="mono-mix", help="How to make mono: mix all channels or select one channel")
    parser.add_argument("--channel", type=int, default=1, help="1-based channel index when --source-mode channel")
    parser.add_argument("--keep-standard-wav", action="store_true", help="Also save a full standard WAV beside chunk files")
    return parser.parse_args()


def sox_standardize_cmd(src, dst, source_mode="mono-mix", channel=1, start=None, duration=None):
    remix_arg = "-" if source_mode == "mono-mix" else str(channel)
    cmd = ["sox", str(src), "-c", "1", "-r", "16000", "-b", "16", str(dst), "remix", remix_arg]
    if start is not None:
        cmd.extend(["trim", f"{start:.3f}"])
        if duration is not None:
            cmd.append(f"{duration:.3f}")
    return cmd


def convert_audio(src, dst, source_mode, channel, start=None, duration=None):
    cmd = sox_standardize_cmd(src, dst, source_mode=source_mode, channel=channel, start=start, duration=duration)
    started = time.time()
    rc, output = run_capture(cmd)
    return {
        "cmd": cmd,
        "return_code": rc,
        "elapsed_seconds": round(time.time() - started, 3),
        "output": output,
        "path": str(dst),
    }


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def run_chunked(args, out_dir, audio_info, sampler):
    duration = audio_info.get("duration_seconds")
    if not duration:
        raise RuntimeError("cannot determine audio duration; install/fix soxi or provide a readable audio file")
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunk_results_path = out_dir / "chunk_results.jsonl"
    num_chunks = int(math.ceil(duration / args.chunk_seconds))
    transcripts = []
    chunk_results = []
    total_asr_elapsed = 0.0
    total_convert_elapsed = 0.0
    log(f"[STANDARD] chunked full coverage: chunk_seconds={args.chunk_seconds}, num_chunks={num_chunks}")
    for idx in range(num_chunks):
        start = idx * args.chunk_seconds
        chunk_duration = max(0.0, min(args.chunk_seconds, duration - start))
        wav_path = chunks_dir / f"chunk_{idx:04d}_{start:.0f}s.wav"
        asr_log_path = chunks_dir / f"chunk_{idx:04d}.asr.log"
        transcript_path = chunks_dir / f"chunk_{idx:04d}.txt"
        log(f"[CHUNK {idx + 1}/{num_chunks}] convert start={start:.3f}s duration={chunk_duration:.3f}s")
        sampler.set_phase("convert")
        conv = convert_audio(args.audio, wav_path, args.source_mode, args.channel, start=start, duration=chunk_duration)
        total_convert_elapsed += conv["elapsed_seconds"]
        if conv["return_code"] != 0:
            conv["status"] = "convert_failed"
            append_jsonl(chunk_results_path, conv)
            chunk_results.append(conv)
            log(f"[CHUNK {idx + 1}/{num_chunks}] convert_failed rc={conv['return_code']}")
            continue
        sampler.set_phase("asr")
        log(f"[CHUNK {idx + 1}/{num_chunks}] asr start wav={wav_path}")
        asr = run_asr_once(
            args.asr_dir,
            args.asr_model_dir,
            wav_path,
            asr_log_path,
            sampler=sampler,
            target_name=f"asr_chunk_{idx:04d}",
            asr_mode=args.asr_mode,
            regex=args.asr_transcript_regex,
        )
        total_asr_elapsed += asr["elapsed_seconds"]
        transcript_path.write_text(asr["transcript"], encoding="utf-8")
        transcripts.append(asr["transcript"])
        item = {
            "index": idx,
            "start_seconds": round(start, 3),
            "duration_seconds": round(chunk_duration, 3),
            "standard_wav": str(wav_path),
            "convert": conv,
            "asr": {
                "cmd": asr["cmd"],
                "log": asr["log"],
                "return_code": asr["return_code"],
                "elapsed_seconds": asr["elapsed_seconds"],
                "extract_method": asr["extract_method"],
                "transcript_chars": asr["transcript_chars"],
                "transcript_path": str(transcript_path),
            },
        }
        append_jsonl(chunk_results_path, item)
        chunk_results.append(item)
        log(f"[CHUNK {idx + 1}/{num_chunks}] asr done rc={asr['return_code']} elapsed={asr['elapsed_seconds']}s chars={asr['transcript_chars']}")
    return "\n".join(t for t in transcripts if t).strip(), {
        "chunked": True,
        "chunk_seconds": args.chunk_seconds,
        "num_chunks": num_chunks,
        "total_convert_elapsed_seconds": round(total_convert_elapsed, 3),
        "total_asr_elapsed_seconds": round(total_asr_elapsed, 3),
        "chunk_results": chunk_results,
        "chunk_results_jsonl": str(chunk_results_path),
    }


def run_one_shot(args, out_dir, sampler):
    standard_wav = out_dir / "standard_mono_16k.wav"
    log(f"[STANDARD] one-shot convert full audio -> {standard_wav}")
    sampler.set_phase("convert")
    conv = convert_audio(args.audio, standard_wav, args.source_mode, args.channel)
    write_json(out_dir / "convert_result.json", conv)
    if conv["return_code"] != 0:
        raise RuntimeError(f"sox conversion failed: {conv['output']}")
    standard_info = soxi_info(standard_wav)
    write_json(out_dir / "standard_audio_info.json", standard_info)
    sampler.set_phase("asr")
    log(f"[STANDARD] one-shot ASR start wav={standard_wav}")
    asr = run_asr_once(
        args.asr_dir,
        args.asr_model_dir,
        standard_wav,
        out_dir / "asr_raw.log",
        sampler=sampler,
        target_name="asr_standard_wav",
        asr_mode=args.asr_mode,
        regex=args.asr_transcript_regex,
    )
    write_json(out_dir / "asr_cmd.json", asr["cmd"])
    return asr["transcript"], {
        "chunked": False,
        "standard_wav": str(standard_wav),
        "standard_audio_info": standard_info,
        "convert": conv,
        "total_convert_elapsed_seconds": conv["elapsed_seconds"],
        "total_asr_elapsed_seconds": asr["elapsed_seconds"],
        "asr": {
            "return_code": asr["return_code"],
            "elapsed_seconds": asr["elapsed_seconds"],
            "extract_method": asr["extract_method"],
            "transcript_chars": asr["transcript_chars"],
            "log": asr["log"],
        },
    }


def main():
    args = parse_args()
    out_dir = prepare_out_dir(args.out_dir, args.overwrite)
    log("[ASR-STANDARD] start standard mono-WAV long-audio evaluation")
    log(f"[ASR-STANDARD] source_audio={args.audio}")
    log(f"[ASR-STANDARD] source_mode={args.source_mode}, channel={args.channel}, chunk_seconds={args.chunk_seconds}")
    log(f"[ASR-STANDARD] out_dir={out_dir}")
    write_json(out_dir / "run_config.json", vars(args))

    source_info = soxi_info(args.audio)
    write_json(out_dir / "source_audio_info.json", source_info)
    log(f"[AUDIO] channels={source_info.get('channels')}, sample_rate={source_info.get('sample_rate')}, duration={source_info.get('duration_seconds')}s")

    reference = ""
    reference_meta = {}
    if args.reference_textgrid:
        reference, reference_meta = extract_textgrid_reference(args.reference_textgrid, args.reference_tier)
        (out_dir / "reference_text.txt").write_text(reference, encoding="utf-8")
        write_json(out_dir / "reference_meta.json", reference_meta)
        log(f"[REF] chars={len(reference)}, intervals={reference_meta.get('interval_count')}, tier={args.reference_tier or 'ALL'}")

    if args.keep_standard_wav and args.chunk_seconds > 0:
        standard_wav = out_dir / "standard_mono_16k_full.wav"
        log(f"[STANDARD] saving full standard WAV -> {standard_wav}")
        conv_full = convert_audio(args.audio, standard_wav, args.source_mode, args.channel)
        write_json(out_dir / "convert_full_result.json", conv_full)
        write_json(out_dir / "standard_full_audio_info.json", soxi_info(standard_wav))

    sampler = MemorySampler(out_dir / "memory_samples.jsonl", interval_s=args.sample_interval)
    sampler.start()
    started = time.time()
    try:
        if args.chunk_seconds and args.chunk_seconds > 0:
            transcript, run_meta = run_chunked(args, out_dir, source_info, sampler)
        else:
            transcript, run_meta = run_one_shot(args, out_dir, sampler)
    finally:
        sampler.stop()
    wall_elapsed = round(time.time() - started, 3)
    memory = sampler.summary()
    write_json(out_dir / "memory_summary.json", memory)

    (out_dir / "transcript_full.txt").write_text(transcript, encoding="utf-8")
    audio_duration = source_info.get("duration_seconds")
    asr_elapsed = run_meta.get("total_asr_elapsed_seconds", 0.0)
    flags = completeness_flags(audio_duration, asr_elapsed, len(transcript), len(reference))
    metrics = distance_metrics(transcript, reference) if reference else {}
    report = {
        "status": "ok" if transcript else "asr_empty",
        "mode": "standard-mono-16k-wav",
        "source_audio": args.audio,
        "source_audio_info": source_info,
        "source_mode": args.source_mode,
        "channel": args.channel if args.source_mode == "channel" else None,
        "target_format": "mono 16000Hz 16-bit PCM WAV",
        "reference_textgrid": args.reference_textgrid,
        "reference_tier": args.reference_tier,
        "reference_meta": reference_meta,
        "wall_elapsed_seconds": wall_elapsed,
        "run": run_meta,
        "transcript_chars": len(transcript),
        "reference_chars": len(reference),
        "completeness": flags,
        "metrics": metrics,
        "memory": memory,
        "outputs": {
            "source_audio_info": str(out_dir / "source_audio_info.json"),
            "reference_text": str(out_dir / "reference_text.txt"),
            "transcript_full": str(out_dir / "transcript_full.txt"),
            "asr_eval": str(out_dir / "asr_eval.json"),
            "memory_summary": str(out_dir / "memory_summary.json"),
            "memory_samples": str(out_dir / "memory_samples.jsonl"),
        },
    }
    write_json(out_dir / "asr_eval.json", report)
    log(f"[ASR-STANDARD] done status={report['status']}, asr_elapsed_total={asr_elapsed}s, wall={wall_elapsed}s, rtf={flags.get('rtf')}")
    log(f"[ASR-STANDARD] transcript_chars={len(transcript)}, reference_chars={len(reference)}, suspicious={flags.get('suspicious')}")
    if transcript:
        log(f"[ASR-STANDARD] transcript_preview={preview_text(transcript)}")
    log(f"[OUTPUT] asr_eval={out_dir / 'asr_eval.json'}")
    log(f"[OUTPUT] transcript={out_dir / 'transcript_full.txt'}")
    return 0 if transcript else 2


if __name__ == "__main__":
    raise SystemExit(main())
