#!/usr/bin/env python3
"""Compare speaker diarization RTTM against TextGrid speaker tiers.

This script is intended for quick offline evaluation of anonymous speaker
clusters. It finds the best one-to-one mapping from predicted speaker IDs to
TextGrid tier names by maximizing overlapped speech time, then reports simple
coverage and speaker accuracy metrics.
"""

import argparse
import itertools
import json
import pathlib
import re
from collections import defaultdict


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


def parse_rttm(path):
    intervals = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3])
        duration = float(parts[4])
        if duration <= 0:
            continue
        intervals.append({"start": start, "end": start + duration, "speaker": parts[7]})
    return sorted(intervals, key=lambda item: (item["start"], item["end"], item["speaker"]))


def overlap_seconds(left, right):
    return max(0.0, min(left["end"], right["end"]) - max(left["start"], right["start"]))


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


def labels_active_at(intervals, timestamp):
    return {item["speaker"] for item in intervals if item["start"] <= timestamp < item["end"]}


def evaluate_by_sampling(predicted, reference, mapping, step):
    end_time = max([item["end"] for item in predicted + reference], default=0.0)
    counts = defaultdict(int)
    confusion = defaultdict(lambda: defaultdict(int))

    timestamp = 0.0
    while timestamp < end_time:
        ref_labels = labels_active_at(reference, timestamp)
        pred_raw = labels_active_at(predicted, timestamp)
        pred_mapped = {mapping.get(label, f"UNMAPPED:{label}") for label in pred_raw}

        counts["total"] += 1
        if ref_labels:
            counts["ref_speech"] += 1
        if pred_raw:
            counts["pred_speech"] += 1
        if ref_labels and pred_raw:
            counts["both_speech"] += 1
            counts["speaker_eval"] += 1
            if ref_labels & pred_mapped:
                counts["speaker_hit"] += 1
        elif ref_labels and not pred_raw:
            counts["miss"] += 1
        elif pred_raw and not ref_labels:
            counts["false_alarm"] += 1

        if ref_labels and pred_raw:
            ref_label = sorted(ref_labels)[0]
            pred_label = sorted(pred_mapped)[0]
            confusion[ref_label][pred_label] += 1

        timestamp += step

    seconds = {key: round(value * step, 3) for key, value in counts.items()}
    speaker_eval = counts["speaker_eval"]
    ref_speech = counts["ref_speech"]
    pred_speech = counts["pred_speech"]
    both_speech = counts["both_speech"]

    return {
        "duration_seconds": round(end_time, 3),
        "sample_step_seconds": step,
        "seconds": seconds,
        "speaker_accuracy_on_overlap": round(counts["speaker_hit"] / speaker_eval, 6) if speaker_eval else None,
        "speech_recall": round(both_speech / ref_speech, 6) if ref_speech else None,
        "speech_precision": round(both_speech / pred_speech, 6) if pred_speech else None,
        "confusion_sample_counts": {ref: dict(items) for ref, items in confusion.items()},
    }


def main():
    parser = argparse.ArgumentParser(description="Compare RTTM diarization output with TextGrid speaker tiers.")
    parser.add_argument("--rttm", required=True, help="Predicted RTTM file from diarization pipeline")
    parser.add_argument("--textgrid", required=True, help="Reference TextGrid file")
    parser.add_argument("--step", type=float, default=0.1, help="Sampling step in seconds for simple metrics")
    parser.add_argument("--out-json", help="Optional path to write JSON report")
    args = parser.parse_args()

    predicted = parse_rttm(args.rttm)
    reference = parse_textgrid(args.textgrid)
    pred_labels, ref_labels, matrix = build_overlap_matrix(predicted, reference)
    mapping, mapping_overlap = best_label_mapping(pred_labels, ref_labels, matrix)
    sampled = evaluate_by_sampling(predicted, reference, mapping, args.step)

    report = {
        "pred_speakers": pred_labels,
        "ref_speakers": ref_labels,
        "pred_speaker_count": len(pred_labels),
        "ref_speaker_count": len(ref_labels),
        "pred_segments": len(predicted),
        "ref_segments": len(reference),
        "mapping_pred_to_ref": mapping,
        "mapping_overlap_seconds": round(mapping_overlap, 3),
        "overlap_matrix_seconds": {
            pred: {ref: round(value, 3) for ref, value in refs.items()}
            for pred, refs in matrix.items()
        },
        "sampled_metrics": sampled,
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)

    if args.out_json:
        out_path = pathlib.Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
