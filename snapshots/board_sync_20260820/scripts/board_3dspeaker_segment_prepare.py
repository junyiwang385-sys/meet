#!/usr/bin/env python3
"""Run 3D-Speaker on board and prepare ASR WAV segments.

This board-side script does the front half of the speaker pipeline:

source FLAC/WAV -> mono16k WAV -> 3D-Speaker RTTM -> segment_plan -> cut WAVs

It intentionally does not require TextGrid. TextGrid is only for offline diagnosis.
"""

import argparse
import csv
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import wave


DEFAULT_3DSPEAKER_DIR = "/userdata/3D-Speaker"


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def human_size(num_bytes):
    value = float(num_bytes)
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if value < 1024.0 or unit == "TiB":
            return f"{value:.2f} {unit}"
        value /= 1024.0


def run_cmd(cmd, log_path=None, cwd=None, env=None, timeout=None):
    started = time.time()
    if log_path:
        pathlib.Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "wb") as fh:
            proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
        output = pathlib.Path(log_path).read_text(encoding="utf-8", errors="replace")
    else:
        proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        output = proc.stdout
    return {"cmd": cmd, "return_code": proc.returncode, "elapsed_seconds": round(time.time() - started, 3), "log": str(log_path) if log_path else None, "output_tail": output[-4000:]}


def wav_duration(path):
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def normalize_audio(source_audio, output_wav, trim_duration=0.0, overwrite=False):
    output_wav = pathlib.Path(output_wav)
    if output_wav.exists() and not overwrite:
        return {"skipped": True, "output": str(output_wav), "duration_seconds": round(wav_duration(output_wav), 3)}
    cmd = ["sox", str(source_audio), "-r", "16000", "-c", "1", "-b", "16", str(output_wav)]
    if trim_duration and trim_duration > 0:
        cmd.extend(["trim", "0", str(trim_duration)])
    result = run_cmd(cmd)
    if result["return_code"] != 0:
        raise RuntimeError("sox normalize failed:\n" + result.get("output_tail", ""))
    result["output"] = str(output_wav)
    result["duration_seconds"] = round(wav_duration(output_wav), 3)
    return result


def parse_rttm(path):
    rows = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3])
        end = start + float(parts[4])
        if end > start:
            rows.append({"start": start, "end": end, "speaker": parts[7], "source": "rttm"})
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def apply_padding(rows, pad, audio_duration):
    out = []
    for row in rows:
        item = dict(row)
        item["start"] = max(0.0, row["start"] - pad)
        item["end"] = min(audio_duration, row["end"] + pad)
        if item["end"] > item["start"]:
            out.append(item)
    return sorted(out, key=lambda item: (item["start"], item["end"], item["speaker"]))


def split_long_segments(rows, max_segment):
    if max_segment <= 0:
        return rows
    out = []
    for row in rows:
        if row["end"] - row["start"] <= max_segment:
            out.append(row)
            continue
        start = row["start"]
        while start < row["end"]:
            end = min(row["end"], start + max_segment)
            item = dict(row)
            item["start"] = start
            item["end"] = end
            item["source"] = row.get("source", "segment") + "_split"
            out.append(item)
            start = end
    return out


def merge_known(rows, merge_gap, max_segment):
    rows = sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))
    merged = []
    for row in rows:
        if not merged:
            merged.append(dict(row))
            continue
        prev = merged[-1]
        if row["speaker"] == prev["speaker"] and row["start"] - prev["end"] <= merge_gap:
            prev["end"] = max(prev["end"], row["end"])
            prev["source"] = "rttm_merged"
        else:
            merged.append(dict(row))
    return split_long_segments(merged, max_segment)


def union_coverage(rows):
    spans = sorted((row["start"], row["end"]) for row in rows)
    if not spans:
        return []
    merged = []
    cur_start, cur_end = spans[0]
    for start, end in spans[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            merged.append({"start": cur_start, "end": cur_end})
            cur_start, cur_end = start, end
    merged.append({"start": cur_start, "end": cur_end})
    return merged


def gaps_from_coverage(coverage, audio_duration, min_gap):
    gaps = []
    cursor = 0.0
    for span in coverage:
        if span["start"] - cursor >= min_gap:
            gaps.append({"start": cursor, "end": span["start"], "speaker": "unknown", "source": "gap_fallback"})
        cursor = max(cursor, span["end"])
    if audio_duration - cursor >= min_gap:
        gaps.append({"start": cursor, "end": audio_duration, "speaker": "unknown", "source": "gap_fallback"})
    return gaps


def merge_unknown(gaps, merge_gap, max_segment):
    gaps = sorted(gaps, key=lambda item: (item["start"], item["end"]))
    merged = []
    for gap in gaps:
        if not merged:
            merged.append(dict(gap))
            continue
        prev = merged[-1]
        if gap["start"] - prev["end"] <= merge_gap:
            prev["end"] = max(prev["end"], gap["end"])
            prev["source"] = "gap_fallback_merged"
        else:
            merged.append(dict(gap))
    return split_long_segments(merged, max_segment)


def round_segment(row, index):
    return {
        "index": index,
        "start": round(row["start"], 3),
        "end": round(row["end"], 3),
        "duration": round(row["end"] - row["start"], 3),
        "speaker": row["speaker"],
        "source": row.get("source", "segment"),
    }


def build_segment_plan(rttm_path, audio_duration, args):
    raw = parse_rttm(rttm_path)
    padded = apply_padding(raw, args.pad, audio_duration)
    known = merge_known(padded, args.known_merge_gap, args.max_known_segment)
    raw_gaps = gaps_from_coverage(union_coverage(known), audio_duration, args.unknown_min_gap)
    unknown = merge_unknown(raw_gaps, args.unknown_merge_gap, args.max_unknown_segment)
    plan = sorted(known + unknown, key=lambda item: (item["start"], item["end"], item["speaker"]))
    plan_rows = [round_segment(row, idx) for idx, row in enumerate(plan)]
    return raw, known, unknown, plan_rows


def safe_speaker_name(value):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(value))


def cut_segments(audio_path, plan_rows, out_audio_dir, min_duration=0.05):
    out_audio_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with wave.open(str(audio_path), "rb") as src:
        params = src.getparams()
        sample_rate = src.getframerate()
        total_frames = src.getnframes()
        duration = total_frames / float(sample_rate)
        for seg in plan_rows:
            start = max(0.0, min(float(seg["start"]), duration))
            end = max(0.0, min(float(seg["end"]), duration))
            if end - start < min_duration:
                continue
            start_frame = max(0, int(round(start * sample_rate)))
            end_frame = min(total_frames, int(round(end * sample_rate)))
            frame_count = max(0, end_frame - start_frame)
            if frame_count <= 0:
                continue
            filename = f"seg_{seg['index']:04d}_{safe_speaker_name(seg['speaker'])}_{start:.3f}_{end:.3f}.wav"
            out_path = out_audio_dir / filename
            src.setpos(start_frame)
            frames = src.readframes(frame_count)
            with wave.open(str(out_path), "wb") as dst:
                dst.setparams(params)
                dst.writeframes(frames)
            item = dict(seg)
            item.update({
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "file": str(out_path),
                "file_name": filename,
                "size_bytes": out_path.stat().st_size,
                "size_human": human_size(out_path.stat().st_size),
            })
            written.append(item)
    return written


def write_csv(path, rows):
    if not rows:
        return
    with pathlib.Path(path).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def find_rttm(out_dir):
    candidates = sorted(pathlib.Path(out_dir).rglob("*.rttm"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No RTTM found under {out_dir}")
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description="Board 3D-Speaker -> segment plan -> cut WAV preparation.")
    parser.add_argument("--source-audio", required=True, help="Original FLAC/WAV input")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--3dspeaker-dir", default=DEFAULT_3DSPEAKER_DIR)
    parser.add_argument("--python", default=sys.executable, help="Python executable in the 3D-Speaker conda env")
    parser.add_argument("--infer-script", help="Override infer_diarization.py path")
    parser.add_argument("--reuse-normalized-wav", action="store_true")
    parser.add_argument("--trim-duration", type=float, default=0.0, help="For smoke tests: only keep first N seconds before diarization")
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--known-merge-gap", type=float, default=0.5)
    parser.add_argument("--unknown-min-gap", type=float, default=0.5)
    parser.add_argument("--unknown-merge-gap", type=float, default=0.5)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)
    parser.add_argument("--min-segment-duration", type=float, default=0.05)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not args.overwrite:
        raise FileExistsError(f"out-dir exists and is not empty: {out_dir}; use --overwrite")
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    source_audio = pathlib.Path(args.source_audio)
    normalized_wav = out_dir / "input_mono16k.wav"
    log("normalizing source audio to mono 16k WAV")
    normalize_report = normalize_audio(source_audio, normalized_wav, args.trim_duration, overwrite=args.overwrite or not args.reuse_normalized_wav)
    duration = float(normalize_report["duration_seconds"])

    infer_script = pathlib.Path(args.infer_script) if args.infer_script else pathlib.Path(args.__dict__["3dspeaker_dir"]) / "speakerlab" / "bin" / "infer_diarization.py"
    diarization_out = out_dir / "3dspeaker_out"
    diarization_out.mkdir(parents=True, exist_ok=True)
    diar_cmd = [str(args.python), str(infer_script), "--wav", str(normalized_wav), "--out_dir", str(diarization_out)]
    env = dict(os.environ)
    env.setdefault("MODELSCOPE_CACHE", "/userdata/modelscope_cache")
    log("running 3D-Speaker diarization")
    diar_report = run_cmd(diar_cmd, log_path=logs_dir / "3dspeaker.log", cwd=args.__dict__["3dspeaker_dir"], env=env)
    if diar_report["return_code"] != 0:
        raise RuntimeError("3D-Speaker failed, see log: " + str(logs_dir / "3dspeaker.log"))

    rttm_path = find_rttm(diarization_out)
    log(f"found RTTM: {rttm_path}")
    raw, known, unknown, plan_rows = build_segment_plan(rttm_path, duration, args)

    segment_plan_dir = out_dir / "segment_plan"
    segment_plan_dir.mkdir(parents=True, exist_ok=True)
    (segment_plan_dir / "segment_plan.json").write_text(json.dumps(plan_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(segment_plan_dir / "segment_plan.csv", plan_rows)

    log("cutting segment WAVs")
    cut_dir = out_dir / "cut_audio"
    wav_segments_dir = cut_dir / "wav_segments"
    cut_rows = cut_segments(normalized_wav, plan_rows, wav_segments_dir, min_duration=args.min_segment_duration)
    (cut_dir / "cut_segments.json").write_text(json.dumps(cut_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(cut_dir / "cut_segments.csv", cut_rows)

    source_size = source_audio.stat().st_size
    normalized_size = normalized_wav.stat().st_size
    cut_size = sum(row["size_bytes"] for row in cut_rows)
    plan_union = union_coverage(plan_rows)
    plan_union_seconds = sum(row["end"] - row["start"] for row in plan_union)
    summary = {
        "source_audio": str(source_audio),
        "source_audio_size_human": human_size(source_size),
        "normalized_wav": str(normalized_wav),
        "normalized_wav_size_human": human_size(normalized_size),
        "audio_duration_seconds": round(duration, 3),
        "rttm": str(rttm_path),
        "wav_segments_dir": str(wav_segments_dir),
        "cut_segments_csv": str(cut_dir / "cut_segments.csv"),
        "segment_plan_json": str(segment_plan_dir / "segment_plan.json"),
        "raw_rttm_segments": len(raw),
        "known_segments_after_merge_split": len(known),
        "unknown_segments_after_merge_split": len(unknown),
        "total_asr_segments": len(cut_rows),
        "known_seconds_sum": round(sum(row["end"] - row["start"] for row in known), 3),
        "unknown_seconds_sum": round(sum(row["end"] - row["start"] for row in unknown), 3),
        "plan_union_covered_seconds": round(plan_union_seconds, 3),
        "plan_union_covered_ratio": round(plan_union_seconds / duration, 6) if duration else None,
        "cut_wav_segments_size_human": human_size(cut_size),
        "cut_vs_normalized_wav_ratio": round(cut_size / normalized_size, 6) if normalized_size else None,
        "storage_keep_source_and_segments_human": human_size(source_size + cut_size),
        "storage_keep_normalized_and_segments_human": human_size(normalized_size + cut_size),
        "normalize_report": normalize_report,
        "diarization_report": diar_report,
    }
    (out_dir / "board_3dspeaker_segment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote reports to: {out_dir}")
    print(f"- {out_dir / 'board_3dspeaker_segment_summary.json'}")
    print(f"- {segment_plan_dir / 'segment_plan.json'}")
    print(f"- {cut_dir / 'cut_segments.csv'}")
    print(f"- {wav_segments_dir}")


if __name__ == "__main__":
    main()
