#!/usr/bin/env python3
"""Side-by-side batch ASR path for RK1828.

Keeps meeting_spk_asr_v1.py and the validated one-shot runner untouched. This
script reuses its diarization/chunk planning helpers, cuts the same WAV chunks,
then invokes rknn_qwen3_asr_batch_demo once for all pending jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import meeting_spk_asr_v1 as stable
except ImportError:
    import meeting_spk_asr_v1 as stable


DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/asr_spk_batch_v1"
DEFAULT_BATCH_DEMO_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo"
DEFAULT_BATCH_BINARY = "rknn_qwen3_asr_batch_demo"


class BatchError(RuntimeError):
    pass


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Side-by-side Qwen3-ASR batch runner for RK1828 speaker chunks"
    )
    parser.add_argument("--audio-file", default=stable.DEFAULT_AUDIO)
    parser.add_argument("--diarization-file", default=stable.DEFAULT_DIARIZATION)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch-demo-dir", default=DEFAULT_BATCH_DEMO_DIR)
    parser.add_argument("--batch-binary", default=DEFAULT_BATCH_BINARY)
    parser.add_argument("--asr-model-dir", default=stable.DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--asr-encoder-device", default="0xff")
    parser.add_argument("--asr-llm-device", default="0xff")
    parser.add_argument("--batch-timeout", type=int, default=3600)

    parser.add_argument("--max-asr-sec", type=float, default=30.0)
    parser.add_argument("--min-asr-sec", type=float, default=1.0)
    parser.add_argument("--min-target-asr-sec", type=float, default=8.0)
    parser.add_argument("--merge-same-speaker", dest="merge_same_speaker", action="store_true", default=True)
    parser.add_argument("--no-merge-same-speaker", dest="merge_same_speaker", action="store_false")
    parser.add_argument("--merge-gap-sec", type=float, default=3.2)
    parser.add_argument("--bridge-fragment-sec", type=float, default=4.0)
    parser.add_argument("--pad-sec", type=float, default=0.3)
    parser.add_argument("--skip-boundary", action="store_true")
    parser.add_argument("--min-boundary-sec", type=float, default=1.0)
    parser.add_argument("--include-fragments", action="store_true")
    parser.add_argument("--min-fragment-sec", type=float, default=2.0)
    parser.add_argument("--include-unknown", action="store_true")
    parser.add_argument("--turn-merge-gap", type=float, default=1.0)

    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--cut-only", action="store_true")
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args(argv)


def require_batch_runtime(args: argparse.Namespace) -> Tuple[Path, List[Path]]:
    demo_dir = Path(args.batch_demo_dir)
    binary = demo_dir / args.batch_binary
    model_dir = Path(args.asr_model_dir)
    stable.require_dir(demo_dir, "batch demo dir")
    stable.require_executable(binary, "batch ASR binary")
    stable.require_file(demo_dir / "mel_128_filters.txt", "mel filter file")
    stable.require_dir(demo_dir / "lib", "batch ASR lib dir")
    stable.require_dir(model_dir, "ASR model dir")
    model_files = [
        model_dir / "encoder.rknn",
        model_dir / "encoder.weight",
        model_dir / "llm.rknn",
        model_dir / "llm.weight",
        model_dir / "llm.tokenizer.gguf",
        model_dir / "llm.embed.bin",
    ]
    for path in model_files:
        stable.require_file(path, f"ASR model file {path.name}")
    return binary, model_files


def read_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if not path.exists():
        return records, warnings
    for line_no, raw in enumerate(stable.read_text(path).splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            warnings.append(f"ignored malformed JSONL line {line_no}: {exc}")
            continue
        if not isinstance(value, dict) or not str(value.get("job_id", "")).strip():
            warnings.append(f"ignored invalid JSONL record at line {line_no}")
            continue
        records.append(value)
    return records, warnings


def latest_records(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for record in records:
        latest[str(record["job_id"])] = record
    return latest


def successful_ids(records: List[Dict[str, Any]]) -> set[str]:
    ok: set[str] = set()
    for record in records:
        job_id = str(record["job_id"])
        if record.get("status") == "ok" and str(record.get("text", "")).strip():
            ok.add(job_id)
        elif job_id in ok:
            ok.remove(job_id)
    return ok


def write_manifest(path: Path, jobs: List[Dict[str, Any]], chunks_dir: Path) -> None:
    lines = []
    for job in jobs:
        job_id = str(job["id"])
        wav_path = (chunks_dir / job["wav_name"]).resolve()
        if "\t" in job_id or "\n" in job_id or "\t" in str(wav_path) or "\n" in str(wav_path):
            raise BatchError(f"manifest field contains tab/newline: job={job_id}")
        lines.append(f"{job_id}\t{wav_path}")
    stable.write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def run_batch(
    args: argparse.Namespace,
    manifest: Path,
    result_jsonl: Path,
    runner_log: Path,
    append: bool,
) -> Dict[str, Any]:
    binary, model_files = require_batch_runtime(args)
    demo_dir = binary.parent
    cmd = [str(binary)] + [str(path) for path in model_files] + [
        args.asr_encoder_device,
        args.asr_llm_device,
        str(manifest),
        str(result_jsonl),
    ]
    if append:
        cmd.append("--append")
    if args.stop_on_error:
        cmd.append("--stop-on-error")

    env = os.environ.copy()
    lib_dir = str(demo_dir / "lib")
    env["LD_LIBRARY_PATH"] = lib_dir + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    started = time.time()
    with runner_log.open("w", encoding="utf-8", errors="replace") as log_file:
        proc = subprocess.run(
            cmd,
            cwd=str(demo_dir),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            timeout=args.batch_timeout,
            check=False,
        )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "elapsed_sec": time.time() - started,
        "runner_log": str(runner_log),
    }


def aggregate_results(
    jobs: List[Dict[str, Any]],
    chunks_dir: Path,
    records: List[Dict[str, Any]],
    runner_log: Path,
) -> List[Dict[str, Any]]:
    latest = latest_records(records)
    results: List[Dict[str, Any]] = []
    for job in jobs:
        result = dict(job)
        result["wav_path"] = str(chunks_dir / job["wav_name"])
        result["raw_log"] = str(runner_log)
        record = latest.get(str(job["id"]))
        if record is None:
            result.update({"status": "missing", "text": "", "error": "no batch result record"})
        else:
            result.update({
                "status": record.get("status", "unknown"),
                "text": str(record.get("text", "")).strip(),
                "error": str(record.get("error", "")),
                "elapsed_sec": record.get("elapsed_sec"),
                "audio_latency_ms": record.get("audio_latency_ms"),
                "llm_elapsed_ms": record.get("llm_elapsed_ms"),
                "prefill_tokens": record.get("prefill_tokens"),
                "decode_tokens": record.get("decode_tokens"),
                "attempt": record.get("attempt"),
            })
        results.append(result)
    return results


def write_outputs(
    args: argparse.Namespace,
    out_dir: Path,
    audio_file: Path,
    diar_file: Path,
    wav_info: Dict[str, Any],
    segments: List[Dict[str, Any]],
    asr_units: List[Dict[str, Any]],
    jobs: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    batch_run: Optional[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    turns = stable.build_turns(results, args.turn_merge_gap)
    meeting_transcript = "\n".join(stable.transcript_lines(turns))
    chunk_transcript = "\n".join(stable.transcript_lines(results))
    ok = sum(1 for item in results if item.get("status") == "ok" and item.get("text"))
    failed = sum(1 for item in results if item.get("status") not in {"ok", "cut_only"})
    stats = {
        "source_segment_count": len(segments),
        "asr_unit_count": len(asr_units),
        "asr_chunk_count": len(jobs),
        "result_count": len(results),
        "ok": ok,
        "failed": failed,
        "cut_only": bool(args.cut_only),
        "batch_elapsed_sec": batch_run.get("elapsed_sec") if batch_run else None,
    }
    final = {
        "audio_file": str(audio_file),
        "diarization_file": str(diar_file),
        "out_dir": str(out_dir),
        "wav_info": wav_info,
        "args": vars(args),
        "stats": stats,
        "warnings": warnings,
        "batch_run": batch_run,
        "asr_units": asr_units,
        "chunks": results,
        "turns": turns,
        "meeting_transcript": meeting_transcript,
    }
    stable.write_json(out_dir / "asr_spk_batch_v1_result.json", final)
    stable.write_json(out_dir / "asr_batch_chunks.json", results)
    stable.write_json(out_dir / "asr_batch_turns.json", turns)
    stable.write_text(out_dir / "chunk_transcript_batch.txt", chunk_transcript + ("\n" if chunk_transcript else ""))
    stable.write_text(out_dir / "meeting_transcript_batch.txt", meeting_transcript + ("\n" if meeting_transcript else ""))
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    audio_file = Path(args.audio_file)
    diar_file = Path(args.diarization_file)
    out_dir = Path(args.out_dir)
    chunks_dir = out_dir / "chunks_wav"
    manifest = out_dir / "asr_batch_manifest.tsv"
    pending_manifest = out_dir / "asr_batch_pending.tsv"
    result_jsonl = out_dir / "asr_batch_results.jsonl"
    runner_log = out_dir / "asr_batch_runner.log"

    stable.require_file(audio_file, "audio file")
    wav_info = stable.get_wav_info(audio_file)
    if wav_info["channels"] != 1:
        raise BatchError(f"expected mono WAV, got channels={wav_info['channels']}: {audio_file}")

    segments = stable.load_diarization(diar_file)
    jobs, asr_units = stable.make_asr_plan(segments, args, float(wav_info["duration"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    plan = {
        "audio_file": str(audio_file),
        "diarization_file": str(diar_file),
        "wav_info": wav_info,
        "args": vars(args),
        "source_segment_count": len(segments),
        "asr_unit_count": len(asr_units),
        "asr_chunk_count": len(jobs),
        "asr_units": asr_units,
        "chunks": jobs,
    }
    stable.write_json(out_dir / "asr_chunk_plan.json", plan)
    write_manifest(manifest, jobs, chunks_dir)

    print("audio:", audio_file)
    print("diarization:", diar_file)
    print("out_dir:", out_dir)
    print("source_segments:", len(segments))
    print("asr_units:", len(asr_units))
    print("asr_chunks:", len(jobs))
    print("plan:", out_dir / "asr_chunk_plan.json")

    if args.plan_only:
        return 0

    for job in jobs:
        wav_path = chunks_dir / job["wav_name"]
        if args.force or not wav_path.exists():
            stable.cut_wav(audio_file, wav_path, float(job["cut_start"]), float(job["cut_end"]))

    if args.cut_only:
        results = []
        for job in jobs:
            item = dict(job)
            item.update({"status": "cut_only", "text": "", "wav_path": str(chunks_dir / job["wav_name"])})
            results.append(item)
        stats = write_outputs(
            args, out_dir, audio_file, diar_file, wav_info, segments, asr_units, jobs, results, None, []
        )
        print("stats:", json.dumps(stats, ensure_ascii=False))
        return 0

    old_records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if args.resume and not args.force:
        old_records, warnings = read_jsonl(result_jsonl)
    elif result_jsonl.exists():
        result_jsonl.unlink()

    done_ids = successful_ids(old_records) if args.resume and not args.force else set()
    pending_jobs = [job for job in jobs if str(job["id"]) not in done_ids]
    write_manifest(pending_manifest, pending_jobs, chunks_dir)
    print("cached_ok:", len(done_ids))
    print("pending:", len(pending_jobs))

    batch_run: Optional[Dict[str, Any]] = None
    if pending_jobs:
        batch_run = run_batch(
            args,
            pending_manifest,
            result_jsonl,
            runner_log,
            append=bool(old_records),
        )
        print("batch_returncode:", batch_run["returncode"])
        print("batch_elapsed_sec:", f"{batch_run['elapsed_sec']:.3f}")
    else:
        print("all chunks are already cached")

    records, read_warnings = read_jsonl(result_jsonl)
    warnings.extend(read_warnings)
    results = aggregate_results(jobs, chunks_dir, records, runner_log)
    stats = write_outputs(
        args, out_dir, audio_file, diar_file, wav_info, segments, asr_units, jobs, results, batch_run, warnings
    )

    print("DONE")
    print("stats:", json.dumps(stats, ensure_ascii=False))
    print("result_json:", out_dir / "asr_spk_batch_v1_result.json")
    print("meeting_transcript:", out_dir / "meeting_transcript_batch.txt")
    print("runner_log:", runner_log)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
    except (BatchError, stable.V1Error) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
