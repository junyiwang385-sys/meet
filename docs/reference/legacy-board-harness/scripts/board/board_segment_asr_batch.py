#!/usr/bin/env python3
"""Run persistent Qwen3-ASR batch inference for diarization-cut WAV files.

The RKNN models are loaded once by rknn_qwen3_asr_batch_demo. This wrapper
creates its headerless TSV manifest, runs all selected WAV files, joins JSONL
results with cut_segments.csv metadata, and writes the timeline artifacts used
by the diarization evaluator and meeting-summary LLM.
"""

import argparse
import csv
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import wave


DEFAULT_ASR_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo"
DEFAULT_ASR_MODEL_DIR = "/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn"
RUNNER_NAME = "rknn_qwen3_asr_batch_demo"
SEGMENT_NAME_RE = re.compile(r"seg_(\d+)_([^_]+)_([0-9.]+)_([0-9.]+)\.wav$")
ACCEPTED_STATUSES = {"ok", "transcript_empty"}


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def write_json(path, value):
    pathlib.Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def model_file(model_dir, name):
    path = pathlib.Path(model_dir) / name
    if not path.is_file():
        raise FileNotFoundError(f"missing ASR model file: {path}")
    return str(path)


def build_runner_cmd(args, manifest_path, results_path):
    runner = pathlib.Path(args.asr_dir) / RUNNER_NAME
    if not runner.is_file():
        raise FileNotFoundError(f"batch ASR runner not found: {runner}")
    return [
        str(runner),
        model_file(args.asr_model_dir, "encoder.rknn"),
        model_file(args.asr_model_dir, "encoder.weight"),
        model_file(args.asr_model_dir, "llm.rknn"),
        model_file(args.asr_model_dir, "llm.weight"),
        model_file(args.asr_model_dir, "llm.tokenizer.gguf"),
        model_file(args.asr_model_dir, "llm.embed.bin"),
        args.encoder_core,
        args.llm_core,
        str(manifest_path),
        str(results_path),
    ]


def parse_segment_name(path):
    match = SEGMENT_NAME_RE.fullmatch(path.name)
    if not match:
        return None
    return {
        "index": int(match.group(1)),
        "speaker": match.group(2),
        "start": float(match.group(3)),
        "end": float(match.group(4)),
        "source": "file_name",
        "audio": str(path),
        "audio_name": path.name,
    }


def load_manifest(path, wav_dir):
    rows = {}
    if not path:
        return rows
    with pathlib.Path(path).open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            name = row.get("file_name") or pathlib.Path(row.get("file", "")).name
            if not name:
                continue
            start = float(row["start"])
            end = float(row["end"])
            rows[name] = {
                "index": int(row["index"]),
                "speaker": str(row["speaker"]),
                "start": start,
                "end": end,
                "duration": float(row.get("duration") or (end - start)),
                "source": row.get("source", ""),
                "audio": str(wav_dir / name),
                "audio_name": name,
            }
    return rows


def discover_segments(wav_dir, metadata_manifest=None):
    wav_dir = pathlib.Path(wav_dir)
    if not wav_dir.is_dir():
        raise FileNotFoundError(f"WAV directory not found: {wav_dir}")
    metadata = load_manifest(metadata_manifest, wav_dir)
    segments = []
    for wav_path in sorted(wav_dir.glob("seg_*.wav")):
        item = metadata.get(wav_path.name) or parse_segment_name(wav_path)
        if item is None:
            continue
        item["audio"] = str(wav_path)
        item["audio_name"] = wav_path.name
        item["job_id"] = wav_path.stem
        item.setdefault("duration", item["end"] - item["start"])
        segments.append(item)
    segments.sort(key=lambda item: item["index"])
    if not segments:
        raise ValueError(f"no seg_*.wav files found in {wav_dir}")
    return segments


def inspect_wav(path):
    try:
        with wave.open(str(path), "rb") as wav:
            return {
                "channels": wav.getnchannels(),
                "sample_rate": wav.getframerate(),
                "sample_width_bytes": wav.getsampwidth(),
                "frames": wav.getnframes(),
                "duration_seconds": round(wav.getnframes() / wav.getframerate(), 6),
                "compression": wav.getcomptype(),
            }
    except (OSError, wave.Error) as exc:
        raise ValueError(f"cannot read WAV {path}: {exc}") from exc


def validate_audio(segments):
    formats = {}
    invalid = []
    for segment in segments:
        info = inspect_wav(segment["audio"])
        segment["wav_info"] = info
        key = f"{info['channels']}ch/{info['sample_rate']}Hz/{info['sample_width_bytes'] * 8}bit/{info['compression']}"
        formats[key] = formats.get(key, 0) + 1
        if (
            info["channels"] != 1
            or info["sample_rate"] != 16000
            or info["sample_width_bytes"] != 2
            or info["compression"] != "NONE"
        ):
            invalid.append({"audio": segment["audio"], "format": key})
    if invalid:
        raise ValueError(
            "batch ASR requires mono 16 kHz 16-bit PCM WAV; invalid files: "
            + json.dumps(invalid[:10], ensure_ascii=False)
        )
    return formats


def write_runner_manifest(path, segments):
    with pathlib.Path(path).open("w", encoding="utf-8", newline="") as fh:
        for segment in segments:
            fh.write(f"{segment['job_id']}\t{segment['audio']}\n")


def load_jsonl(path):
    rows = []
    with pathlib.Path(path).open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL line {line_number}: {exc}") from exc
    return rows


def combine_results(segments, runner_rows):
    by_id = {}
    duplicate_ids = []
    for row in runner_rows:
        job_id = str(row.get("job_id", ""))
        if job_id in by_id:
            duplicate_ids.append(job_id)
        by_id[job_id] = row
    if duplicate_ids:
        raise ValueError(f"duplicate job_id values in runner results: {duplicate_ids[:10]}")

    results = []
    missing = []
    for segment in segments:
        runner = by_id.get(segment["job_id"])
        if runner is None:
            missing.append(segment["job_id"])
            runner = {
                "status": "missing_result",
                "text": "",
                "error": "runner did not produce this job",
            }
        status = str(runner.get("status", "unknown"))
        text = re.sub(r"\s+", " ", str(runner.get("text") or "")).strip()
        item = {key: value for key, value in segment.items() if key != "wav_info"}
        item.update({
            "return_code": 0 if status in ACCEPTED_STATUSES else -1,
            "status": status,
            "text": text,
            "text_chars": len(text),
            "error": str(runner.get("error") or ""),
            "elapsed_seconds": runner.get("elapsed_sec"),
            "audio_duration_seconds": runner.get("audio_duration_sec"),
            "llm_elapsed_ms": runner.get("llm_elapsed_ms"),
            "prefill_tokens": runner.get("prefill_tokens"),
            "decode_tokens": runner.get("decode_tokens"),
            "attempt": runner.get("attempt"),
        })
        results.append(item)
    extra = sorted(set(by_id) - {item["job_id"] for item in segments})
    return results, missing, extra


def write_csv(path, rows):
    fields = [
        "index", "start", "end", "duration", "speaker", "source",
        "audio_name", "audio", "job_id", "return_code", "status",
        "elapsed_seconds", "audio_duration_seconds", "llm_elapsed_ms",
        "prefill_tokens", "decode_tokens", "attempt", "text_chars", "error", "text",
    ]
    with pathlib.Path(path).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})


def format_time(seconds):
    minutes = int(float(seconds) // 60)
    remain = float(seconds) - minutes * 60
    return f"{minutes:02d}:{remain:06.3f}"


def write_timeline(path, rows, include_empty=False):
    lines = []
    for row in rows:
        text = row.get("text", "").replace("\n", " ").strip()
        if not text and not include_empty:
            continue
        speaker = str(row.get("speaker", "unknown"))
        if speaker != "unknown" and not speaker.startswith("speaker_"):
            speaker = f"speaker_{speaker}"
        lines.append(
            f"[{row['index']:04d}]"
            f"[{format_time(row['start'])}-{format_time(row['end'])}]"
            f"[{speaker}] {text}"
        )
    pathlib.Path(path).write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )


def is_relative_to(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def prepare_out_dir(path, overwrite, protected_paths):
    out_dir = pathlib.Path(path).resolve()
    if out_dir == pathlib.Path(out_dir.anchor):
        raise ValueError("refusing filesystem root as out-dir")
    for protected in protected_paths:
        if not protected:
            continue
        protected = pathlib.Path(protected).resolve()
        if protected == out_dir or is_relative_to(protected, out_dir):
            raise ValueError(f"refusing out-dir that contains an input path: {protected}")
    if out_dir.exists() and any(out_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"out-dir is not empty: {out_dir}; use --overwrite")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def parse_args():
    parser = argparse.ArgumentParser(
        description="Persistent batch ASR for diarization-cut WAV segments on RK1828."
    )
    parser.add_argument("--wav-dir", required=True, help="Directory containing seg_*.wav")
    parser.add_argument("--manifest", help="cut_segments.csv used to preserve exact timeline metadata")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--encoder-core", default="0xff")
    parser.add_argument("--llm-core", default="0xff")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="Run only first N selected segments; 0 means all")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    out_dir = prepare_out_dir(
        args.out_dir,
        args.overwrite,
        [args.wav_dir, args.manifest, args.asr_dir, args.asr_model_dir],
    )
    segments = [
        item for item in discover_segments(args.wav_dir, args.manifest)
        if item["index"] >= args.start_index
    ]
    if args.limit > 0:
        segments = segments[:args.limit]
    if not segments:
        raise ValueError("no segments selected")

    audio_formats = validate_audio(segments)
    runner_manifest = out_dir / "manifest.tsv"
    raw_results = out_dir / "results.jsonl"
    runner_log = out_dir / "batch_runner.log"
    write_runner_manifest(runner_manifest, segments)

    cmd = build_runner_cmd(args, runner_manifest, raw_results)
    write_json(out_dir / "batch_runner_cmd.json", cmd)
    env = dict(os.environ)
    lib_dir = str(pathlib.Path(args.asr_dir) / "lib")
    env["LD_LIBRARY_PATH"] = lib_dir + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )

    log(f"segments selected: {len(segments)}")
    log(f"audio formats: {audio_formats}")
    log(f"runner: {cmd[0]}")
    started = time.time()
    with runner_log.open("wb") as fh:
        proc = subprocess.run(
            cmd,
            cwd=args.asr_dir,
            stdout=fh,
            stderr=subprocess.STDOUT,
            env=env,
        )
    wall_elapsed = round(time.time() - started, 3)
    if not raw_results.is_file():
        raise RuntimeError(
            f"batch runner produced no results.jsonl; rc={proc.returncode}, log={runner_log}"
        )

    runner_rows = load_jsonl(raw_results)
    results, missing, extra = combine_results(segments, runner_rows)
    status_counts = {}
    for item in results:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    true_failures = [item for item in results if item["status"] not in ACCEPTED_STATUSES]

    summary = {
        "wav_dir": str(args.wav_dir),
        "metadata_manifest": str(args.manifest) if args.manifest else None,
        "runner_manifest": str(runner_manifest),
        "out_dir": str(out_dir),
        "asr_dir": str(args.asr_dir),
        "asr_model_dir": str(args.asr_model_dir),
        "runner": RUNNER_NAME,
        "runner_return_code": proc.returncode,
        "segment_count": len(results),
        "completed_count": len(results) - len(missing),
        "success_count": len(results) - len(true_failures),
        "failed_count": len(true_failures),
        "empty_text_count": sum(not item["text"] for item in results),
        "status_counts": status_counts,
        "missing_result_count": len(missing),
        "extra_result_count": len(extra),
        "total_text_chars": sum(item["text_chars"] for item in results),
        "total_elapsed_seconds": wall_elapsed,
        "asr_elapsed_seconds_sum": round(
            sum(float(item["elapsed_seconds"] or 0.0) for item in results), 3
        ),
        "audio_duration_seconds_sum": round(
            sum(float(item["audio_duration_seconds"] or item["duration"]) for item in results), 3
        ),
        "prefill_tokens_sum": sum(int(item["prefill_tokens"] or 0) for item in results),
        "decode_tokens_sum": sum(int(item["decode_tokens"] or 0) for item in results),
        "audio_formats": audio_formats,
        "note": "transcript_empty is an accepted completed result; runner may return 1 when empty segments exist",
    }

    write_json(out_dir / "segment_transcripts.json", results)
    write_csv(out_dir / "segment_transcripts.csv", results)
    write_timeline(out_dir / "llm_input_timeline.txt", results)
    write_timeline(out_dir / "llm_input_timeline_with_empty.txt", results, include_empty=True)
    write_json(out_dir / "batch_asr_summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote reports to: {out_dir}")
    print(f"- {raw_results}")
    print(f"- {out_dir / 'segment_transcripts.json'}")
    print(f"- {out_dir / 'llm_input_timeline.txt'}")
    return 2 if true_failures or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
