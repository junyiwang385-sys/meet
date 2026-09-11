#!/usr/bin/env python3
"""Scan RTTM padding values against TextGrid speaker/time reference.

For each padding value, this script expands every RTTM segment by +/- pad seconds,
recomputes the best anonymous-speaker mapping to TextGrid tiers, and reports
speech coverage plus speaker accuracy metrics.
"""

import argparse
import csv
import itertools
import json
import pathlib
import re


def parse_textgrid(path):
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    item_blocks = re.findall(
        r"item \[\d+\]:\s*(.*?)(?=\n\s*item \[\d+\]:|\Z)",
        text,
        flags=re.DOTALL,
    )
    intervals = []
    for block in item_blocks:
        name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
        if not name_match:
            continue
        speaker = name_match.group(1)
        interval_blocks = re.findall(
            r"intervals \[\d+\]:\s*(.*?)(?=\n\s*intervals \[\d+\]:|\Z)",
            block,
            flags=re.DOTALL,
        )
        for interval in interval_blocks:
            xmin = re.search(r"xmin\s*=\s*([0-9.]+)", interval)
            xmax = re.search(r"xmax\s*=\s*([0-9.]+)", interval)
            txt = re.search(r'text\s*=\s*"((?:[^"]|"")*)"', interval)
            if not xmin or not xmax or not txt:
                continue
            value = txt.group(1).replace('""', '"').strip()
            if not value or value == "<sil>":
                continue
            start = float(xmin.group(1))
            end = float(xmax.group(1))
            if end <= start:
                continue
            intervals.append({"start": start, "end": end, "speaker": speaker, "text": value})
    return sorted(intervals, key=lambda item: (item["start"], item["end"], item["speaker"]))


def parse_rttm_base(path):
    intervals = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3])
        end = start + float(parts[4])
        if end <= start:
            continue
        intervals.append({"start": start, "end": end, "speaker": parts[7]})
    return sorted(intervals, key=lambda item: (item["start"], item["end"], item["speaker"]))


def apply_padding(intervals, pad, audio_end):
    padded = []
    for item in intervals:
        start = max(0.0, item["start"] - pad)
        end = item["end"] + pad
        if audio_end is not None:
            end = min(audio_end, end)
        if end > start:
            padded.append({"start": start, "end": end, "speaker": item["speaker"]})
    return padded


def overlap_seconds(a, b):
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def build_overlap_matrix(predicted, reference):
    pred_labels = sorted({item["speaker"] for item in predicted})
    ref_labels = sorted({item["speaker"] for item in reference})
    matrix = {pred: {ref: 0.0 for ref in ref_labels} for pred in pred_labels}
    for pred in predicted:
        for ref in reference:
            overlap = overlap_seconds(pred, ref)
            if overlap > 0:
                matrix[pred["speaker"]][ref["speaker"]] += overlap
    return pred_labels, ref_labels, matrix


def best_label_mapping(pred_labels, ref_labels, matrix):
    if not pred_labels or not ref_labels:
        return {}, 0.0
    best_score = -1.0
    best_mapping = {}
    if len(pred_labels) <= len(ref_labels):
        for perm in itertools.permutations(ref_labels, len(pred_labels)):
            score = sum(matrix[pred][ref] for pred, ref in zip(pred_labels, perm))
            if score > best_score:
                best_score = score
                best_mapping = dict(zip(pred_labels, perm))
    else:
        for perm in itertools.permutations(pred_labels, len(ref_labels)):
            score = sum(matrix[pred][ref] for pred, ref in zip(perm, ref_labels))
            if score > best_score:
                best_score = score
                best_mapping = {pred: ref for pred, ref in zip(perm, ref_labels)}
    return best_mapping, best_score


def active_labels(intervals, timestamp):
    return {item["speaker"] for item in intervals if item["start"] <= timestamp < item["end"]}


def interval_coverage(ref, predicted):
    total = 0.0
    for pred in predicted:
        total += overlap_seconds(ref, pred)
    duration = ref["end"] - ref["start"]
    return min(total, duration) / duration if duration > 0 else 0.0


def evaluate_padding(base_pred, reference, pad, step, coverage_threshold):
    audio_end = max([item["end"] for item in reference + base_pred], default=0.0)
    predicted = apply_padding(base_pred, pad, audio_end)
    pred_labels, ref_labels, matrix = build_overlap_matrix(predicted, reference)
    mapping, mapping_overlap = best_label_mapping(pred_labels, ref_labels, matrix)

    counts = {
        "total": 0,
        "ref_speech": 0,
        "pred_speech": 0,
        "both_speech": 0,
        "miss": 0,
        "false_alarm": 0,
        "speaker_eval": 0,
        "speaker_hit": 0,
    }

    t = 0.0
    while t < audio_end:
        ref_set = active_labels(reference, t)
        pred_raw = active_labels(predicted, t)
        pred_mapped = {mapping.get(label, f"UNMAPPED:{label}") for label in pred_raw}

        counts["total"] += 1
        if ref_set:
            counts["ref_speech"] += 1
        if pred_raw:
            counts["pred_speech"] += 1
        if ref_set and pred_raw:
            counts["both_speech"] += 1
            counts["speaker_eval"] += 1
            if ref_set & pred_mapped:
                counts["speaker_hit"] += 1
        elif ref_set and not pred_raw:
            counts["miss"] += 1
        elif pred_raw and not ref_set:
            counts["false_alarm"] += 1
        t += step

    missed_intervals = []
    partial_intervals = []
    missed_chars = 0
    partial_chars = 0
    for ref in reference:
        cov = interval_coverage(ref, predicted)
        duration = ref["end"] - ref["start"]
        if cov < coverage_threshold:
            missed_intervals.append(ref)
            missed_chars += len(ref["text"])
        elif cov < 0.95:
            partial_intervals.append(ref)
            partial_chars += len(ref["text"])

    def sec(key):
        return round(counts[key] * step, 3)

    ref_speech = counts["ref_speech"]
    pred_speech = counts["pred_speech"]
    both_speech = counts["both_speech"]
    speaker_eval = counts["speaker_eval"]

    missed_seconds = sum(item["end"] - item["start"] for item in missed_intervals)
    partial_seconds = sum(item["end"] - item["start"] for item in partial_intervals)
    ref_total_seconds = sum(item["end"] - item["start"] for item in reference)

    return {
        "pad_seconds": pad,
        "pred_segments": len(predicted),
        "pred_speaker_count": len(pred_labels),
        "ref_speaker_count": len(ref_labels),
        "mapping_pred_to_ref": mapping,
        "mapping_overlap_seconds": round(mapping_overlap, 3),
        "sample_step_seconds": step,
        "sample_ref_speech_seconds": sec("ref_speech"),
        "sample_pred_speech_seconds": sec("pred_speech"),
        "sample_both_speech_seconds": sec("both_speech"),
        "sample_miss_seconds": sec("miss"),
        "sample_false_alarm_seconds": sec("false_alarm"),
        "speech_recall": round(both_speech / ref_speech, 6) if ref_speech else None,
        "speech_precision": round(both_speech / pred_speech, 6) if pred_speech else None,
        "speaker_accuracy_on_overlap": round(counts["speaker_hit"] / speaker_eval, 6) if speaker_eval else None,
        "interval_ref_speech_seconds": round(ref_total_seconds, 3),
        "interval_missed_count": len(missed_intervals),
        "interval_missed_seconds": round(missed_seconds, 3),
        "interval_missed_ratio": round(missed_seconds / ref_total_seconds, 6) if ref_total_seconds else None,
        "interval_missed_text_chars": missed_chars,
        "interval_partial_count": len(partial_intervals),
        "interval_partial_seconds": round(partial_seconds, 3),
        "interval_partial_text_chars": partial_chars,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan RTTM padding values against TextGrid reference.")
    parser.add_argument("--rttm", required=True)
    parser.add_argument("--textgrid", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pads", default="0,0.3,0.5,0.8,1.0,1.2,1.5,2.0", help="Comma-separated padding seconds")
    parser.add_argument("--step", type=float, default=0.1, help="Sampling step in seconds")
    parser.add_argument("--coverage-threshold", type=float, default=0.5)
    args = parser.parse_args()

    base_pred = parse_rttm_base(args.rttm)
    reference = parse_textgrid(args.textgrid)
    pads = [float(item.strip()) for item in args.pads.split(",") if item.strip()]

    reports = [evaluate_padding(base_pred, reference, pad, args.step, args.coverage_threshold) for pad in pads]

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "padding_scan.json"
    csv_path = out_dir / "padding_scan.csv"
    txt_path = out_dir / "padding_scan.txt"

    result = {
        "rttm": str(args.rttm),
        "textgrid": str(args.textgrid),
        "coverage_threshold": args.coverage_threshold,
        "pads": pads,
        "reports": reports,
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fields = [
        "pad_seconds",
        "speech_recall",
        "speech_precision",
        "speaker_accuracy_on_overlap",
        "sample_miss_seconds",
        "sample_false_alarm_seconds",
        "interval_missed_count",
        "interval_missed_seconds",
        "interval_missed_ratio",
        "interval_missed_text_chars",
        "interval_partial_count",
        "interval_partial_seconds",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for report in reports:
            writer.writerow({key: report.get(key) for key in fields})

    lines = []
    header = (
        f"{'pad':>5} {'recall':>8} {'prec':>8} {'spk_acc':>8} "
        f"{'miss_s':>8} {'fa_s':>8} {'miss_int_s':>11} {'miss_cnt':>8} {'miss_chars':>10}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for report in reports:
        lines.append(
            f"{report['pad_seconds']:5.2f} "
            f"{report['speech_recall'] if report['speech_recall'] is not None else 0:8.4f} "
            f"{report['speech_precision'] if report['speech_precision'] is not None else 0:8.4f} "
            f"{report['speaker_accuracy_on_overlap'] if report['speaker_accuracy_on_overlap'] is not None else 0:8.4f} "
            f"{report['sample_miss_seconds']:8.1f} "
            f"{report['sample_false_alarm_seconds']:8.1f} "
            f"{report['interval_missed_seconds']:11.1f} "
            f"{report['interval_missed_count']:8d} "
            f"{report['interval_missed_text_chars']:10d}"
        )
    text = "\n".join(lines) + "\n"
    txt_path.write_text(text, encoding="utf-8")

    print(text)
    print(f"Wrote: {json_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {txt_path}")


if __name__ == "__main__":
    main()
