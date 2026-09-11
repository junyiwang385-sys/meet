#!/usr/bin/env python3
"""Run CPU 3D-Speaker and absorb short same-speaker-bounded unknown gaps.

This script always rebuilds the preparation output from the original FLAC/WAV:

source audio -> mono16k WAV -> CPU/Torch 3D-Speaker RTTM
-> pad known intervals -> absorb eligible unknown gaps -> segment plan -> cut WAVs
"""

import argparse
import csv
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import wave
from collections import Counter


DEFAULT_3DSPEAKER_DIR = "/userdata/3D-Speaker"
EPSILON = 1.0e-6
DURATION_BINS = [
    ("<1s", 0.0, 1.0),
    ("1-2s", 1.0, 2.0),
    ("2-5s", 2.0, 5.0),
    ("5-10s", 5.0, 10.0),
    ("10-20s", 10.0, 20.0),
    ("20-30s", 20.0, 30.0),
    (">=30s", 30.0, None),
]


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
    return {
        "cmd": cmd,
        "return_code": proc.returncode,
        "elapsed_seconds": round(time.time() - started, 3),
        "log": str(log_path) if log_path else None,
        "output_tail": output[-4000:],
    }


def wav_duration(path):
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def normalize_audio(source_audio, output_wav, trim_duration=0.0):
    cmd = ["sox", str(source_audio), "-r", "16000", "-c", "1", "-b", "16", str(output_wav)]
    if trim_duration and trim_duration > 0:
        cmd.extend(["trim", "0", str(trim_duration)])
    result = run_cmd(cmd)
    if result["return_code"] != 0:
        raise RuntimeError("sox normalize failed:\n" + result.get("output_tail", ""))
    result["output"] = str(output_wav)
    result["duration_seconds"] = round(wav_duration(output_wav), 6)
    return result


def parse_rttm(path):
    rows = []
    for raw_index, line in enumerate(pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3])
        end = start + float(parts[4])
        if end > start:
            rows.append({
                "start": start,
                "end": end,
                "speaker": parts[7],
                "source": "rttm",
                "source_ids": [f"rttm:{raw_index}"],
                "absorbed_gap_ids": [],
            })
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def apply_padding(rows, pad, audio_duration):
    out = []
    for row in rows:
        item = dict(row)
        item["start"] = max(0.0, row["start"] - pad)
        item["end"] = min(audio_duration, row["end"] + pad)
        item["source"] = "rttm_padded"
        item["source_ids"] = list(row.get("source_ids", []))
        item["absorbed_gap_ids"] = list(row.get("absorbed_gap_ids", []))
        if item["end"] > item["start"]:
            out.append(item)
    return sorted(out, key=lambda item: (item["speaker"], item["start"], item["end"]))


def merge_values(left, right):
    return sorted(set(left or []) | set(right or []))


def merge_same_speaker_intervals(rows, epsilon=EPSILON):
    """Merge only overlapping/touching intervals of the same speaker."""
    merged = []
    for row in sorted(rows, key=lambda item: (item["speaker"], item["start"], item["end"])):
        item = dict(row)
        item["source_ids"] = list(row.get("source_ids", []))
        item["absorbed_gap_ids"] = list(row.get("absorbed_gap_ids", []))
        if not merged or merged[-1]["speaker"] != item["speaker"] or item["start"] > merged[-1]["end"] + epsilon:
            merged.append(item)
            continue
        prev = merged[-1]
        prev["end"] = max(prev["end"], item["end"])
        prev["source_ids"] = merge_values(prev.get("source_ids"), item.get("source_ids"))
        prev["absorbed_gap_ids"] = merge_values(prev.get("absorbed_gap_ids"), item.get("absorbed_gap_ids"))
        prev["source"] = "rttm_gap_absorbed_merged" if prev["absorbed_gap_ids"] else "rttm_merged"
    return sorted(merged, key=lambda item: (item["start"], item["end"], item["speaker"]))


def union_coverage(rows):
    spans = sorted((row["start"], row["end"]) for row in rows if row["end"] > row["start"])
    if not spans:
        return []
    merged = []
    cur_start, cur_end = spans[0]
    for start, end in spans[1:]:
        if start <= cur_end + EPSILON:
            cur_end = max(cur_end, end)
        else:
            merged.append({"start": cur_start, "end": cur_end})
            cur_start, cur_end = start, end
    merged.append({"start": cur_start, "end": cur_end})
    return merged


def find_all_uncovered_gaps(coverage, audio_duration):
    gaps = []
    cursor = 0.0
    for span in coverage:
        if span["start"] > cursor + EPSILON:
            gaps.append({"start": cursor, "end": span["start"]})
        cursor = max(cursor, span["end"])
    if audio_duration > cursor + EPSILON:
        gaps.append({"start": cursor, "end": audio_duration})
    if not coverage and audio_duration > 0:
        gaps = [{"start": 0.0, "end": audio_duration}]
    for index, gap in enumerate(gaps):
        gap["gap_id"] = f"gap:{index:04d}"
        gap["duration"] = gap["end"] - gap["start"]
    return gaps


def boundary_speakers(known_rows, gap, epsilon=EPSILON):
    left_rows = [row for row in known_rows if abs(row["end"] - gap["start"]) <= epsilon]
    right_rows = [row for row in known_rows if abs(row["start"] - gap["end"]) <= epsilon]
    return {
        "left_speakers": sorted({row["speaker"] for row in left_rows}),
        "right_speakers": sorted({row["speaker"] for row in right_rows}),
        "left_source_ids": sorted({value for row in left_rows for value in row.get("source_ids", [])}),
        "right_source_ids": sorted({value for row in right_rows for value in row.get("source_ids", [])}),
    }


def classify_gap_for_absorption(gap, known_rows, threshold, audio_duration, epsilon=EPSILON):
    boundary = boundary_speakers(known_rows, gap, epsilon)
    decision = {
        "gap_id": gap["gap_id"],
        "start": gap["start"],
        "end": gap["end"],
        "duration": gap["duration"],
        **boundary,
        "decision": "kept_unknown",
        "assigned_speaker": None,
        "reason": None,
    }
    if gap["start"] <= epsilon:
        decision["reason"] = "leading_gap"
    elif gap["end"] >= audio_duration - epsilon:
        decision["reason"] = "trailing_gap"
    elif gap["duration"] > threshold + epsilon:
        decision["reason"] = "over_threshold"
    elif not boundary["left_speakers"] or not boundary["right_speakers"]:
        decision["reason"] = "missing_boundary"
    elif len(boundary["left_speakers"]) != 1:
        decision["reason"] = "ambiguous_left_boundary"
    elif len(boundary["right_speakers"]) != 1:
        decision["reason"] = "ambiguous_right_boundary"
    elif boundary["left_speakers"][0] != boundary["right_speakers"][0]:
        decision["reason"] = "different_boundary_speakers"
    else:
        decision["decision"] = "absorbed"
        decision["assigned_speaker"] = boundary["left_speakers"][0]
        decision["reason"] = "same_speaker_bounded_short"
    return decision


def apply_gap_absorptions(known_rows, decisions):
    bridges = []
    for decision in decisions:
        if decision["decision"] != "absorbed":
            continue
        bridges.append({
            "start": decision["start"],
            "end": decision["end"],
            "speaker": decision["assigned_speaker"],
            "source": "same_speaker_gap_absorbed",
            "source_ids": [],
            "absorbed_gap_ids": [decision["gap_id"]],
        })
    return merge_same_speaker_intervals(list(known_rows) + bridges), bridges


def split_long_segments(rows, max_segment):
    if max_segment <= 0:
        return [dict(row) for row in rows]
    out = []
    for row in rows:
        if row["end"] - row["start"] <= max_segment + EPSILON:
            out.append(dict(row))
            continue
        start = row["start"]
        while start < row["end"] - EPSILON:
            end = min(row["end"], start + max_segment)
            item = dict(row)
            item["start"] = start
            item["end"] = end
            item["source"] = row.get("source", "segment") + "_split"
            out.append(item)
            start = end
    return out


def unknown_rows_from_gaps(gaps):
    return [{
        "start": gap["start"],
        "end": gap["end"],
        "speaker": "unknown",
        "source": "gap_fallback",
        "source_ids": [],
        "absorbed_gap_ids": [],
    } for gap in gaps]


def round_segment(row, index):
    absorbed_ids = list(row.get("absorbed_gap_ids", []))
    return {
        "index": index,
        "start": round(row["start"], 3),
        "end": round(row["end"], 3),
        "duration": round(row["end"] - row["start"], 3),
        "speaker": row["speaker"],
        "source": row.get("source", "segment"),
        "absorbed_gap_count": len(absorbed_ids),
        "absorbed_gap_ids": ",".join(absorbed_ids),
    }


def build_segment_plan(raw_rows, audio_duration, pad, absorb_unknown_max, max_known_segment, max_unknown_segment):
    padded = apply_padding(raw_rows, pad, audio_duration)
    known_before = merge_same_speaker_intervals(padded)
    initial_gaps = find_all_uncovered_gaps(union_coverage(known_before), audio_duration)
    decisions = [
        classify_gap_for_absorption(gap, known_before, absorb_unknown_max, audio_duration)
        for gap in initial_gaps
    ]
    known_after_unsplit, bridges = apply_gap_absorptions(known_before, decisions)
    remaining_gaps = find_all_uncovered_gaps(union_coverage(known_after_unsplit), audio_duration)
    unknown_unsplit = unknown_rows_from_gaps(remaining_gaps)
    known = split_long_segments(known_after_unsplit, max_known_segment)
    unknown = split_long_segments(unknown_unsplit, max_unknown_segment)
    plan = sorted(known + unknown, key=lambda item: (item["start"], item["end"], item["speaker"]))
    plan_rows = [round_segment(row, index) for index, row in enumerate(plan)]
    return {
        "raw": raw_rows,
        "padded": padded,
        "known_before_absorption": known_before,
        "initial_gaps": initial_gaps,
        "decisions": decisions,
        "bridges": bridges,
        "known_after_absorption_unsplit": known_after_unsplit,
        "remaining_gaps": remaining_gaps,
        "known": known,
        "unknown": unknown,
        "plan_rows": plan_rows,
    }


def validate_segment_plan(result, audio_duration, absorb_unknown_max, max_known_segment, max_unknown_segment):
    for decision in result["decisions"]:
        if decision["decision"] != "absorbed":
            continue
        if decision["duration"] > absorb_unknown_max + EPSILON:
            raise ValueError(f"absorbed gap exceeds threshold: {decision}")
        if len(decision["left_speakers"]) != 1 or decision["left_speakers"] != decision["right_speakers"]:
            raise ValueError(f"absorbed gap has invalid boundaries: {decision}")
    for row in result["known"] + result["unknown"]:
        if row["start"] < -EPSILON or row["end"] > audio_duration + EPSILON or row["end"] <= row["start"]:
            raise ValueError(f"invalid plan interval: {row}")
        limit = max_unknown_segment if row["speaker"] == "unknown" else max_known_segment
        if limit > 0 and row["end"] - row["start"] > limit + EPSILON:
            raise ValueError(f"segment exceeds max duration: {row}")
    indexes = [row["index"] for row in result["plan_rows"]]
    if indexes != list(range(len(indexes))):
        raise ValueError("segment indexes are not contiguous")


def safe_speaker_name(value):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(value))


def cut_segments(audio_path, plan_rows, out_audio_dir, min_duration=0.05):
    out_audio_dir.mkdir(parents=True, exist_ok=True)
    written = []
    skipped = []
    with wave.open(str(audio_path), "rb") as src:
        params = src.getparams()
        sample_rate = src.getframerate()
        total_frames = src.getnframes()
        duration = total_frames / float(sample_rate)
        for seg in plan_rows:
            start = max(0.0, min(float(seg["start"]), duration))
            end = max(0.0, min(float(seg["end"]), duration))
            if end - start < min_duration:
                skipped.append(dict(seg))
                continue
            start_frame = max(0, int(round(start * sample_rate)))
            end_frame = min(total_frames, int(round(end * sample_rate)))
            frame_count = max(0, end_frame - start_frame)
            if frame_count <= 0:
                skipped.append(dict(seg))
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
    return written, skipped


def write_csv(path, rows):
    if not rows:
        return
    with pathlib.Path(path).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def find_rttm(out_dir):
    candidates = sorted(pathlib.Path(out_dir).rglob("*.rttm"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No RTTM found under {out_dir}")
    return candidates[0]


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * fraction
    lower = int(pos)
    upper = min(lower + 1, len(values) - 1)
    weight = pos - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def duration_summary(rows):
    values = [row["end"] - row["start"] for row in rows]
    if not values:
        return {"count": 0, "seconds_sum": 0.0, "bins": {label: 0 for label, _, _ in DURATION_BINS}}
    bins = {
        label: sum(1 for value in values if value >= low and (high is None or value < high))
        for label, low, high in DURATION_BINS
    }
    return {
        "count": len(values),
        "seconds_sum": round(sum(values), 3),
        "mean": round(sum(values) / len(values), 3),
        "min": round(min(values), 3),
        "p25": round(percentile(values, 0.25), 3),
        "p50": round(percentile(values, 0.50), 3),
        "p75": round(percentile(values, 0.75), 3),
        "p90": round(percentile(values, 0.90), 3),
        "max": round(max(values), 3),
        "bins": bins,
    }


def prepare_fresh_out_dir(out_dir, source_audio, speaker_dir, overwrite):
    out_dir = pathlib.Path(out_dir).resolve()
    source_audio = pathlib.Path(source_audio).resolve()
    speaker_dir = pathlib.Path(speaker_dir).resolve()
    anchor = pathlib.Path(out_dir.anchor)
    if out_dir == anchor or out_dir == source_audio or out_dir == speaker_dir:
        raise ValueError(f"unsafe output directory: {out_dir}")
    try:
        out_dir.relative_to(speaker_dir)
    except ValueError:
        pass
    else:
        raise ValueError("output directory must not be inside the 3D-Speaker installation")
    try:
        source_audio.relative_to(out_dir)
    except ValueError:
        pass
    else:
        raise ValueError("output directory contains the source audio")
    if out_dir.exists() and any(out_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"out-dir exists and is not empty: {out_dir}; use --overwrite")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def validate_args(args):
    for name in ["pad", "absorb_unknown_max", "min_segment_duration", "trim_duration"]:
        if getattr(args, name) < 0:
            raise ValueError(f"--{name.replace('_', '-')} must be nonnegative")
    infer_script = pathlib.Path(args.infer_script) if args.infer_script else pathlib.Path(args.__dict__["3dspeaker_dir"]) / "speakerlab" / "bin" / "infer_diarization.py"
    if not infer_script.is_file():
        raise FileNotFoundError(f"infer script not found: {infer_script}")
    if "rknn" in str(infer_script).lower():
        raise ValueError("this script requires the CPU/Torch infer_diarization.py, not an RKNN variant")
    return infer_script.resolve()


def serialize_decisions(decisions):
    rows = []
    for decision in decisions:
        item = dict(decision)
        item["start"] = round(item["start"], 3)
        item["end"] = round(item["end"], 3)
        item["duration"] = round(item["duration"], 3)
        for key in ["left_speakers", "right_speakers", "left_source_ids", "right_source_ids"]:
            item[key] = ",".join(item[key])
        rows.append(item)
    return rows


def main():
    parser = argparse.ArgumentParser(description="CPU 3D-Speaker preparation with conservative short-unknown absorption.")
    parser.add_argument("--source-audio", required=True, help="Original FLAC/WAV input")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--3dspeaker-dir", default=DEFAULT_3DSPEAKER_DIR)
    parser.add_argument("--python", default=sys.executable, help="Python executable in the 3D-Speaker conda env")
    parser.add_argument("--infer-script", help="Stock CPU/Torch infer_diarization.py path")
    parser.add_argument("--trim-duration", type=float, default=0.0, help="For smoke tests: only keep first N seconds")
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--absorb-unknown-max", type=float, default=2.0)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)
    parser.add_argument("--min-segment-duration", type=float, default=0.05)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source_audio = pathlib.Path(args.source_audio).resolve()
    if not source_audio.is_file():
        raise FileNotFoundError(f"source audio not found: {source_audio}")
    infer_script = validate_args(args)
    out_dir = prepare_fresh_out_dir(args.out_dir, source_audio, args.__dict__["3dspeaker_dir"], args.overwrite)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    normalized_wav = out_dir / "input_mono16k.wav"
    log("normalizing source audio to mono 16k WAV")
    normalize_report = normalize_audio(source_audio, normalized_wav, args.trim_duration)
    duration = float(normalize_report["duration_seconds"])

    diarization_out = out_dir / "3dspeaker_out"
    diarization_out.mkdir(parents=True, exist_ok=True)
    diar_cmd = [str(args.python), str(infer_script), "--wav", str(normalized_wav), "--out_dir", str(diarization_out)]
    env = dict(os.environ)
    env.setdefault("MODELSCOPE_CACHE", "/userdata/modelscope_cache")
    env["CUDA_VISIBLE_DEVICES"] = ""
    log("running CPU/Torch 3D-Speaker diarization")
    diar_report = run_cmd(diar_cmd, log_path=logs_dir / "3dspeaker.log", cwd=args.__dict__["3dspeaker_dir"], env=env)
    if diar_report["return_code"] != 0:
        raise RuntimeError("3D-Speaker failed, see log: " + str(logs_dir / "3dspeaker.log"))

    rttm_path = find_rttm(diarization_out)
    log(f"found RTTM: {rttm_path}")
    raw = parse_rttm(rttm_path)
    result = build_segment_plan(
        raw,
        duration,
        args.pad,
        args.absorb_unknown_max,
        args.max_known_segment,
        args.max_unknown_segment,
    )
    validate_segment_plan(result, duration, args.absorb_unknown_max, args.max_known_segment, args.max_unknown_segment)

    segment_plan_dir = out_dir / "segment_plan"
    segment_plan_dir.mkdir(parents=True, exist_ok=True)
    (segment_plan_dir / "segment_plan.json").write_text(json.dumps(result["plan_rows"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(segment_plan_dir / "segment_plan.csv", result["plan_rows"])
    decision_rows = serialize_decisions(result["decisions"])
    (segment_plan_dir / "unknown_gap_decisions.json").write_text(json.dumps(decision_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(segment_plan_dir / "unknown_gap_decisions.csv", decision_rows)
    absorbed = [row for row in decision_rows if row["decision"] == "absorbed"]
    (segment_plan_dir / "absorbed_unknown_gaps.json").write_text(json.dumps(absorbed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    remaining_unknown_rows = [round_segment(row, index) for index, row in enumerate(result["unknown"])]
    (segment_plan_dir / "remaining_unknown_segments.json").write_text(json.dumps(remaining_unknown_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("cutting fresh segment WAVs")
    cut_dir = out_dir / "cut_audio"
    wav_segments_dir = cut_dir / "wav_segments"
    cut_rows, skipped_rows = cut_segments(normalized_wav, result["plan_rows"], wav_segments_dir, args.min_segment_duration)
    (cut_dir / "cut_segments.json").write_text(json.dumps(cut_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(cut_dir / "cut_segments.csv", cut_rows)

    source_size = source_audio.stat().st_size
    normalized_size = normalized_wav.stat().st_size
    cut_size = sum(row["size_bytes"] for row in cut_rows)
    plan_union = union_coverage(result["plan_rows"])
    plan_union_seconds = sum(row["end"] - row["start"] for row in plan_union)
    reason_counts = Counter(row["reason"] for row in result["decisions"])
    absorbed_decisions = [row for row in result["decisions"] if row["decision"] == "absorbed"]
    summary = {
        "source_audio": str(source_audio),
        "source_audio_size_human": human_size(source_size),
        "normalized_wav": str(normalized_wav),
        "normalized_wav_size_human": human_size(normalized_size),
        "audio_duration_seconds": round(duration, 3),
        "infer_script": str(infer_script),
        "rttm": str(rttm_path),
        "wav_segments_dir": str(wav_segments_dir),
        "cut_segments_csv": str(cut_dir / "cut_segments.csv"),
        "segment_plan_json": str(segment_plan_dir / "segment_plan.json"),
        "params": {
            "pad": args.pad,
            "absorb_unknown_max": args.absorb_unknown_max,
            "max_known_segment": args.max_known_segment,
            "max_unknown_segment": args.max_unknown_segment,
            "min_segment_duration": args.min_segment_duration,
        },
        "raw_rttm_segments": len(raw),
        "known_before_absorption_unsplit": len(result["known_before_absorption"]),
        "unknown_gap_count_before": len(result["initial_gaps"]),
        "unknown_gap_seconds_before": round(sum(row["duration"] for row in result["initial_gaps"]), 3),
        "absorbed_unknown_count": len(absorbed_decisions),
        "absorbed_unknown_seconds": round(sum(row["duration"] for row in absorbed_decisions), 3),
        "gap_decision_reason_counts": dict(sorted(reason_counts.items())),
        "known_segments_after_absorption_split": len(result["known"]),
        "remaining_unknown_count_after_split": len(result["unknown"]),
        "remaining_unknown_seconds": round(sum(row["end"] - row["start"] for row in result["unknown"]), 3),
        "total_asr_segments_planned": len(result["plan_rows"]),
        "total_asr_segments": len(cut_rows),
        "skipped_cut_segment_count": len(skipped_rows),
        "skipped_cut_segment_seconds": round(sum(row["duration"] for row in skipped_rows), 3),
        "known_seconds_sum": round(sum(row["end"] - row["start"] for row in result["known"]), 3),
        "unknown_seconds_sum": round(sum(row["end"] - row["start"] for row in result["unknown"]), 3),
        "plan_union_covered_seconds": round(plan_union_seconds, 3),
        "plan_union_covered_ratio": round(plan_union_seconds / duration, 6) if duration else None,
        "duration_distributions": {
            "unknown_gaps_before": duration_summary(result["initial_gaps"]),
            "absorbed_unknown_gaps": duration_summary(absorbed_decisions),
            "known_after_split": duration_summary(result["known"]),
            "unknown_after_split": duration_summary(result["unknown"]),
        },
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
    print(f"- {segment_plan_dir / 'unknown_gap_decisions.csv'}")
    print(f"- {cut_dir / 'cut_segments.csv'}")
    print(f"- {wav_segments_dir}")


if __name__ == "__main__":
    main()
