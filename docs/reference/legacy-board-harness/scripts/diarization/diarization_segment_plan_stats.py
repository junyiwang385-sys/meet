#!/usr/bin/env python3
"""Build and evaluate a diarization ASR segment plan.

The plan contains known speaker segments from RTTM plus unknown fallback gaps.
It is intended to estimate how many ASR chunks will be produced after merging,
and how much TextGrid reference speech/text would be covered.
"""

import argparse
import csv
import itertools
import json
import pathlib
import re
import wave


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


def parse_textgrid(path):
    if not path:
        return []
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    item_blocks = re.findall(r"item \[\d+\]:\s*(.*?)(?=\n\s*item \[\d+\]:|\Z)", text, flags=re.DOTALL)
    rows = []
    for block in item_blocks:
        name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
        if not name_match:
            continue
        speaker = name_match.group(1)
        interval_blocks = re.findall(r"intervals \[\d+\]:\s*(.*?)(?=\n\s*intervals \[\d+\]:|\Z)", block, flags=re.DOTALL)
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
            if end > start:
                rows.append({"start": start, "end": end, "speaker": speaker, "text": value})
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def wav_duration(path):
    if not path:
        return None
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / float(wav.getframerate())


def overlap_seconds(a, b):
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def apply_padding(rows, pad, audio_duration):
    out = []
    for row in rows:
        item = dict(row)
        item["start"] = max(0.0, row["start"] - pad)
        item["end"] = row["end"] + pad
        if audio_duration is not None:
            item["end"] = min(audio_duration, item["end"])
        if item["end"] > item["start"]:
            out.append(item)
    return sorted(out, key=lambda item: (item["start"], item["end"], item["speaker"]))


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


def split_long_segments(rows, max_segment):
    if max_segment <= 0:
        return rows
    out = []
    for row in rows:
        duration = row["end"] - row["start"]
        if duration <= max_segment:
            out.append(row)
            continue
        start = row["start"]
        while start < row["end"]:
            end = min(row["end"], start + max_segment)
            item = dict(row)
            item["start"] = start
            item["end"] = end
            item["source"] = row.get("source", "rttm") + "_split"
            out.append(item)
            start = end
    return out


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
    if audio_duration is not None and audio_duration - cursor >= min_gap:
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


def labels_active_at(rows, timestamp):
    return {row["speaker"] for row in rows if row["start"] <= timestamp < row["end"]}


def build_overlap_matrix(predicted_known, reference):
    pred_labels = sorted({row["speaker"] for row in predicted_known if row["speaker"] != "unknown"})
    ref_labels = sorted({row["speaker"] for row in reference})
    matrix = {pred: {ref: 0.0 for ref in ref_labels} for pred in pred_labels}
    for pred in predicted_known:
        if pred["speaker"] == "unknown":
            continue
        for ref in reference:
            ov = overlap_seconds(pred, ref)
            if ov > 0:
                matrix[pred["speaker"]][ref["speaker"]] += ov
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


def sample_metrics(known_rows, all_rows, reference, step, audio_duration):
    pred_labels, ref_labels, matrix = build_overlap_matrix(known_rows, reference)
    mapping, mapping_overlap = best_label_mapping(pred_labels, ref_labels, matrix)
    counts = {key: 0 for key in [
        "ref_speech", "known_speech", "all_speech", "known_ref_overlap", "all_ref_overlap",
        "known_false_alarm", "all_false_alarm", "known_speaker_eval", "known_speaker_hit",
        "unknown_ref_overlap", "unknown_speech",
    ]}
    unknown_rows = [row for row in all_rows if row["speaker"] == "unknown"]

    t = 0.0
    while t < audio_duration:
        ref_set = labels_active_at(reference, t)
        known_set = labels_active_at(known_rows, t)
        unknown_set = labels_active_at(unknown_rows, t)
        all_set = known_set | unknown_set
        mapped_known = {mapping.get(label, f"UNMAPPED:{label}") for label in known_set}
        if ref_set:
            counts["ref_speech"] += 1
        if known_set:
            counts["known_speech"] += 1
        if all_set:
            counts["all_speech"] += 1
        if known_set and ref_set:
            counts["known_ref_overlap"] += 1
            counts["known_speaker_eval"] += 1
            if mapped_known & ref_set:
                counts["known_speaker_hit"] += 1
        if all_set and ref_set:
            counts["all_ref_overlap"] += 1
        if known_set and not ref_set:
            counts["known_false_alarm"] += 1
        if all_set and not ref_set:
            counts["all_false_alarm"] += 1
        if unknown_set:
            counts["unknown_speech"] += 1
            if ref_set:
                counts["unknown_ref_overlap"] += 1
        t += step

    def ratio(num, den):
        return round(num / den, 6) if den else None

    return {
        "mapping_pred_to_ref": mapping,
        "mapping_overlap_seconds": round(mapping_overlap, 3),
        "known_speech_recall": ratio(counts["known_ref_overlap"], counts["ref_speech"]),
        "all_speech_recall_with_unknown": ratio(counts["all_ref_overlap"], counts["ref_speech"]),
        "known_speech_precision": ratio(counts["known_ref_overlap"], counts["known_speech"]),
        "all_speech_precision_with_unknown": ratio(counts["all_ref_overlap"], counts["all_speech"]),
        "known_speaker_accuracy_on_overlap": ratio(counts["known_speaker_hit"], counts["known_speaker_eval"]),
        "unknown_precision": ratio(counts["unknown_ref_overlap"], counts["unknown_speech"]),
        "seconds": {key: round(value * step, 3) for key, value in counts.items()},
    }


def interval_coverage(interval, rows):
    total = sum(overlap_seconds(interval, row) for row in rows)
    duration = interval["end"] - interval["start"]
    return min(total, duration) / duration if duration > 0 else 0.0


def interval_metrics(rows, reference, threshold):
    total_ref_seconds = sum(ref["end"] - ref["start"] for ref in reference)
    coverages = []
    under = []
    missed = []
    for ref in reference:
        cov = interval_coverage(ref, rows)
        item = dict(ref)
        item["coverage"] = round(cov, 6)
        item["duration"] = round(ref["end"] - ref["start"], 3)
        coverages.append(cov)
        if cov < 0.95:
            under.append(item)
        if cov < threshold:
            missed.append(item)
    return {
        "avg_ref_interval_coverage": round(sum(coverages) / len(coverages), 6) if coverages else None,
        "under_95_count": len(under),
        "under_95_seconds": round(sum(item["duration"] for item in under), 3),
        "missed_count_under_threshold": len(missed),
        "missed_seconds_under_threshold": round(sum(item["duration"] for item in missed), 3),
        "missed_text_chars_under_threshold": sum(len(item["text"]) for item in missed),
        "total_ref_speech_seconds": round(total_ref_seconds, 3),
        "top_under_covered": sorted(under, key=lambda item: item["duration"] * (1 - item["coverage"]), reverse=True)[:30],
    }


def interval_coverage_rows(reference, known_rows, unknown_rows, mapping):
    rows = []
    for idx, ref in enumerate(reference):
        duration = ref["end"] - ref["start"]
        known_overlap = sum(overlap_seconds(ref, row) for row in known_rows)
        unknown_overlap = sum(overlap_seconds(ref, row) for row in unknown_rows)
        all_overlap = min(duration, known_overlap + unknown_overlap)

        speaker_overlaps = {}
        for row in known_rows:
            ov = overlap_seconds(ref, row)
            if ov <= 0:
                continue
            pred_speaker = row["speaker"]
            mapped_speaker = mapping.get(pred_speaker)
            speaker_overlaps[pred_speaker] = speaker_overlaps.get(pred_speaker, 0.0) + ov
            if mapped_speaker:
                speaker_overlaps[f"{pred_speaker}->{mapped_speaker}"] = speaker_overlaps.get(f"{pred_speaker}->{mapped_speaker}", 0.0) + ov

        best_pred = None
        best_pred_overlap = 0.0
        raw_pred_overlaps = {key: value for key, value in speaker_overlaps.items() if "->" not in key}
        if raw_pred_overlaps:
            best_pred, best_pred_overlap = max(raw_pred_overlaps.items(), key=lambda item: item[1])

        rows.append({
            "index": idx,
            "start": round(ref["start"], 3),
            "end": round(ref["end"], 3),
            "duration": round(duration, 3),
            "ref_speaker": ref["speaker"],
            "known_overlap_seconds": round(min(duration, known_overlap), 3),
            "unknown_overlap_seconds": round(min(duration, unknown_overlap), 3),
            "all_overlap_seconds": round(all_overlap, 3),
            "known_coverage": round(min(duration, known_overlap) / duration, 6) if duration > 0 else 0.0,
            "all_coverage_with_unknown": round(all_overlap / duration, 6) if duration > 0 else 0.0,
            "best_pred_speaker": best_pred,
            "best_pred_mapped_to_ref": mapping.get(best_pred) if best_pred is not None else None,
            "best_pred_overlap_seconds": round(best_pred_overlap, 3),
            "text_chars": len(ref.get("text", "")),
            "text": ref.get("text", ""),
        })
    return rows


def segment_quality_rows(known_rows, reference, mapping):
    rows = []
    for idx, seg in enumerate(known_rows):
        mapped_ref = mapping.get(seg["speaker"])
        correct = 0.0
        other = 0.0
        ref_speech = 0.0
        other_speakers = {}
        for ref in reference:
            ov = overlap_seconds(seg, ref)
            if ov <= 0:
                continue
            ref_speech += ov
            if ref["speaker"] == mapped_ref:
                correct += ov
            else:
                other += ov
                other_speakers[ref["speaker"]] = other_speakers.get(ref["speaker"], 0.0) + ov
        duration = seg["end"] - seg["start"]
        no_ref = max(0.0, duration - ref_speech)
        rows.append({
            "index": idx,
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "duration": round(duration, 3),
            "pred_speaker": seg["speaker"],
            "mapped_ref_speaker": mapped_ref,
            "correct_ref_speech_seconds": round(correct, 3),
            "other_ref_speech_seconds": round(other, 3),
            "no_ref_or_silence_seconds": round(no_ref, 3),
            "purity_on_ref_speech": round(correct / (correct + other), 6) if correct + other > 0 else None,
            "other_speaker_leak_ratio_on_ref_speech": round(other / (correct + other), 6) if correct + other > 0 else None,
            "other_ref_speakers": json.dumps({key: round(value, 3) for key, value in sorted(other_speakers.items())}, ensure_ascii=False),
            "source": seg.get("source", "rttm"),
        })
    return rows


def summarize_segment_quality(rows):
    correct = sum(row["correct_ref_speech_seconds"] for row in rows)
    other = sum(row["other_ref_speech_seconds"] for row in rows)
    no_ref = sum(row["no_ref_or_silence_seconds"] for row in rows)
    duration = sum(row["duration"] for row in rows)
    return {
        "known_correct_ref_speech_seconds": round(correct, 3),
        "known_other_ref_speech_seconds": round(other, 3),
        "known_no_ref_or_silence_seconds": round(no_ref, 3),
        "known_segment_seconds": round(duration, 3),
        "known_speaker_purity_on_ref_speech": round(correct / (correct + other), 6) if correct + other > 0 else None,
        "known_other_speaker_leak_ratio_on_ref_speech": round(other / (correct + other), 6) if correct + other > 0 else None,
        "known_no_ref_or_silence_ratio": round(no_ref / duration, 6) if duration > 0 else None,
        "top_leaky_known_segments": sorted(rows, key=lambda item: item["other_ref_speech_seconds"], reverse=True)[:30],
    }


def round_segment(row, index):
    return {
        "index": index,
        "start": round(row["start"], 3),
        "end": round(row["end"], 3),
        "duration": round(row["end"] - row["start"], 3),
        "speaker": row["speaker"],
        "source": row.get("source", "unknown"),
    }


def load_segment_plan(path):
    path = pathlib.Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        with path.open("r", encoding="utf-8", newline="") as fh:
            data = list(csv.DictReader(fh))
    rows = []
    for row in data:
        start = float(row["start"])
        end = float(row["end"])
        if end <= start:
            continue
        rows.append({
            "start": start,
            "end": end,
            "speaker": str(row.get("speaker", "unknown")),
            "source": row.get("source", "segment_plan"),
        })
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def main():
    parser = argparse.ArgumentParser(description="Build or evaluate a known + unknown ASR segment plan.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--rttm", help="Build a segment plan from RTTM")
    input_group.add_argument("--segment-plan", help="Evaluate an existing segment plan JSON/CSV without rebuilding it")
    parser.add_argument("--audio", help="WAV path for duration")
    parser.add_argument("--audio-duration", type=float)
    parser.add_argument("--textgrid")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pad", type=float, default=1.0)
    parser.add_argument("--known-merge-gap", type=float, default=0.5)
    parser.add_argument("--unknown-min-gap", type=float, default=0.5)
    parser.add_argument("--unknown-merge-gap", type=float, default=0.5)
    parser.add_argument("--max-known-segment", type=float, default=30.0)
    parser.add_argument("--max-unknown-segment", type=float, default=20.0)
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--coverage-threshold", type=float, default=0.5)
    args = parser.parse_args()

    reference = parse_textgrid(args.textgrid) if args.textgrid else []
    if args.segment_plan:
        raw = []
        padded = []
        raw_gaps = []
        plan = load_segment_plan(args.segment_plan)
        known = [row for row in plan if row["speaker"] != "unknown"]
        unknown = [row for row in plan if row["speaker"] == "unknown"]
        duration = args.audio_duration or (wav_duration(args.audio) if args.audio else None)
        if duration is None:
            ends = [row["end"] for row in plan]
            ends.extend(row["end"] for row in reference)
            duration = max(ends) if ends else 0.0
        input_mode = "segment_plan"
    else:
        raw = parse_rttm(args.rttm)
        duration = args.audio_duration or (wav_duration(args.audio) if args.audio else None)
        if duration is None:
            ends = [row["end"] for row in raw]
            ends.extend(row["end"] for row in reference)
            duration = max(ends) if ends else 0.0
        padded = apply_padding(raw, args.pad, duration)
        known = merge_known(padded, args.known_merge_gap, args.max_known_segment)
        known_union = union_coverage(known)
        raw_gaps = gaps_from_coverage(known_union, duration, args.unknown_min_gap)
        unknown = merge_unknown(raw_gaps, args.unknown_merge_gap, args.max_unknown_segment)
        plan = sorted(known + unknown, key=lambda item: (item["start"], item["end"], item["speaker"]))
        input_mode = "rttm"

    known_seconds = sum(row["end"] - row["start"] for row in known)
    unknown_seconds = sum(row["end"] - row["start"] for row in unknown)
    plan_union = union_coverage(plan)
    plan_union_seconds = sum(row["end"] - row["start"] for row in plan_union)

    summary = {
        "input_mode": input_mode,
        "rttm": str(args.rttm) if args.rttm else None,
        "segment_plan_input": str(args.segment_plan) if args.segment_plan else None,
        "audio": str(args.audio) if args.audio else None,
        "textgrid": str(args.textgrid) if args.textgrid else None,
        "audio_duration_seconds": round(duration, 3),
        "params": {
            "pad": args.pad,
            "known_merge_gap": args.known_merge_gap,
            "unknown_min_gap": args.unknown_min_gap,
            "unknown_merge_gap": args.unknown_merge_gap,
            "max_known_segment": args.max_known_segment,
            "max_unknown_segment": args.max_unknown_segment,
            "sample_step": args.step,
            "coverage_threshold": args.coverage_threshold,
        },
        "counts": {
            "raw_rttm_segments": len(raw),
            "known_segments_after_merge_split": len(known),
            "unknown_segments_after_merge_split": len(unknown),
            "total_asr_segments": len(plan),
        },
        "seconds": {
            "known_segment_seconds_sum": round(known_seconds, 3),
            "unknown_segment_seconds_sum": round(unknown_seconds, 3),
            "plan_union_covered_seconds": round(plan_union_seconds, 3),
            "plan_union_covered_ratio": round(plan_union_seconds / duration, 6) if duration else None,
        },
    }

    interval_rows = []
    quality_rows = []
    if reference:
        summary["sample_metrics"] = sample_metrics(known, plan, reference, args.step, duration)
        summary["known_interval_metrics"] = interval_metrics(known, reference, args.coverage_threshold)
        summary["all_interval_metrics_with_unknown"] = interval_metrics(plan, reference, args.coverage_threshold)
        mapping = summary["sample_metrics"]["mapping_pred_to_ref"]
        interval_rows = interval_coverage_rows(reference, known, unknown, mapping)
        quality_rows = segment_quality_rows(known, reference, mapping)
        summary["known_segment_quality"] = summarize_segment_quality(quality_rows)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_rows = [round_segment(row, idx) for idx, row in enumerate(plan)]
    known_rows = [round_segment(row, idx) for idx, row in enumerate(known)]
    unknown_rows = [round_segment(row, idx) for idx, row in enumerate(unknown)]

    (out_dir / "segment_plan_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "segment_plan.json").write_text(json.dumps(plan_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "known_segments.json").write_text(json.dumps(known_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "unknown_segments.json").write_text(json.dumps(unknown_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if interval_rows:
        (out_dir / "gt_interval_coverage.json").write_text(json.dumps(interval_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if quality_rows:
        (out_dir / "known_segment_quality.json").write_text(json.dumps(quality_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (out_dir / "segment_plan.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["index", "start", "end", "duration", "speaker", "source"])
        writer.writeheader()
        writer.writerows(plan_rows)

    if interval_rows:
        with (out_dir / "gt_interval_coverage.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(interval_rows[0].keys()))
            writer.writeheader()
            writer.writerows(interval_rows)

    if quality_rows:
        with (out_dir / "known_segment_quality.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(quality_rows[0].keys()))
            writer.writeheader()
            writer.writerows(quality_rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote reports to: {out_dir}")
    print(f"- {out_dir / 'segment_plan_summary.json'}")
    print(f"- {out_dir / 'segment_plan.json'}")
    print(f"- {out_dir / 'segment_plan.csv'}")


if __name__ == "__main__":
    main()
