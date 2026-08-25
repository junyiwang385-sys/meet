#!/usr/bin/env python3
"""Evaluate segment ASR transcripts against TextGrid reference.

This is a diagnostic script for the board batch ASR result. It compares the
board-produced [start,end,speaker,text] timeline with TextGrid reference text,
and also writes an LLM-ready timeline transcript.
"""

import argparse
import csv
import itertools
import json
import pathlib
import re


def normalize_transcript(text):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def normalize_for_distance(text):
    text = re.sub(r"<[^>]+>", "", text or "").lower()
    return "".join(re.findall(r"[0-9a-zA-Z一-鿿]", text))


def tokenize_for_distance(text):
    text = re.sub(r"<[^>]+>", "", text or "").lower()
    return re.findall(r"[一-鿿]|[0-9a-zA-Z]+", text)


def levenshtein(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + (0 if ca == cb else 1)))
        previous = current
    return previous[-1]


def distance_metrics(hypothesis, reference, max_cells=80_000_000):
    ref_chars = normalize_for_distance(reference)
    hyp_chars = normalize_for_distance(hypothesis)
    char_cells = len(ref_chars) * len(hyp_chars)
    result = {
        "reference_chars_normalized": len(ref_chars),
        "hypothesis_chars_normalized": len(hyp_chars),
        "char_distance": None,
        "cer": None,
        "char_distance_skipped": char_cells > max_cells,
        "max_distance_cells": max_cells,
    }
    if ref_chars and char_cells <= max_cells:
        dist = levenshtein(hyp_chars, ref_chars)
        result["char_distance"] = dist
        result["cer"] = round(dist / len(ref_chars), 6)
    ref_tokens = tokenize_for_distance(reference)
    hyp_tokens = tokenize_for_distance(hypothesis)
    token_cells = len(ref_tokens) * len(hyp_tokens)
    result.update({
        "reference_tokens": len(ref_tokens),
        "hypothesis_tokens": len(hyp_tokens),
        "token_distance": None,
        "token_error_rate": None,
        "token_distance_skipped": token_cells > max_cells,
    })
    if ref_tokens and token_cells <= max_cells:
        dist = levenshtein(hyp_tokens, ref_tokens)
        result["token_distance"] = dist
        result["token_error_rate"] = round(dist / len(ref_tokens), 6)
    return result


def parse_textgrid(path):
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


def load_segment_transcripts(path):
    rows = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    out = []
    for row in rows:
        start = float(row["start"])
        end = float(row["end"])
        if end <= start:
            continue
        item = dict(row)
        item["start"] = start
        item["end"] = end
        item["duration"] = float(row.get("duration") or (end - start))
        item["index"] = int(row["index"])
        item["speaker"] = str(row.get("speaker", "unknown"))
        item["text"] = normalize_transcript(row.get("text", ""))
        item["text_chars"] = len(item["text"])
        out.append(item)
    return sorted(out, key=lambda item: (item["start"], item["end"], item["index"]))


def overlap_seconds(a, b):
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def build_overlap_matrix(segments, reference):
    pred_labels = sorted({row["speaker"] for row in segments if row["speaker"] != "unknown"})
    ref_labels = sorted({row["speaker"] for row in reference})
    matrix = {pred: {ref: 0.0 for ref in ref_labels} for pred in pred_labels}
    for seg in segments:
        if seg["speaker"] == "unknown":
            continue
        for ref in reference:
            ov = overlap_seconds(seg, ref)
            if ov > 0:
                matrix[seg["speaker"]][ref["speaker"]] += ov
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


def format_time(seconds):
    seconds = float(seconds)
    minutes = int(seconds // 60)
    remain = seconds - minutes * 60
    return f"{minutes:02d}:{remain:06.3f}"


def speaker_label(speaker):
    if speaker == "unknown" or speaker.startswith("speaker_"):
        return speaker
    return f"speaker_{speaker}"


def mapped_speaker_label(speaker, mapping):
    if speaker == "unknown":
        return "unknown"
    mapped = mapping.get(speaker)
    if mapped:
        return f"{mapped}(pred:{speaker})"
    return speaker_label(speaker)


def write_gt_timeline(path, reference):
    lines = []
    for idx, row in enumerate(sorted(reference, key=lambda item: (item["start"], item["end"], item["speaker"]))):
        text = normalize_transcript(row.get("text", ""))
        if not text:
            continue
        lines.append(f"[{idx:04d}][{format_time(row['start'])}-{format_time(row['end'])}][{row['speaker']}] {text}")
    pathlib.Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_mapped_asr_timeline(path, segments, mapping, include_empty=False):
    lines = []
    for seg in sorted(segments, key=lambda item: (item["start"], item["end"], item["index"])):
        text = normalize_transcript(seg.get("text", ""))
        if not text and not include_empty:
            continue
        lines.append(f"[{seg['index']:04d}][{format_time(seg['start'])}-{format_time(seg['end'])}][{mapped_speaker_label(seg['speaker'], mapping)}] {text}")
    pathlib.Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_segment_overlap_preview(path, rows):
    lines = []
    for row in rows:
        asr_text = normalize_transcript(row.get("asr_text", ""))
        gt_text = normalize_transcript(row.get("gt_text_by_time_overlap", ""))
        matched_text = normalize_transcript(row.get("matched_speaker_gt_text_by_time_overlap", ""))
        speaker = row.get("speaker", "unknown")
        mapped = row.get("mapped_ref_speaker") or "unknown"
        header = f"[{row['index']:04d}][{format_time(row['start'])}-{format_time(row['end'])}][pred:{speaker}->gt:{mapped}]"
        lines.append(header)
        lines.append(f"ASR: {asr_text}")
        lines.append(f"GT : {gt_text}")
        if matched_text and matched_text != gt_text:
            lines.append(f"GT(same speaker): {matched_text}")
        lines.append("")
    pathlib.Path(path).write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")


def join_text(rows):
    return normalize_transcript(" ".join(row.get("text", "") for row in rows if row.get("text")))


def segment_gt_rows(segments, reference, mapping):
    rows = []
    for seg in segments:
        overlaps = []
        ref_texts = []
        mapped_speaker = mapping.get(seg["speaker"])
        matched_speaker_ref_texts = []
        unknown_or_other_ref_texts = []
        for ref in reference:
            ov = overlap_seconds(seg, ref)
            if ov <= 0:
                continue
            overlaps.append({"speaker": ref["speaker"], "overlap_seconds": ov, "text": ref["text"]})
            ref_texts.append(ref["text"])
            if mapped_speaker and ref["speaker"] == mapped_speaker:
                matched_speaker_ref_texts.append(ref["text"])
            else:
                unknown_or_other_ref_texts.append(ref["text"])
        gt_text = normalize_transcript(" ".join(ref_texts))
        matched_text = normalize_transcript(" ".join(matched_speaker_ref_texts))
        row = {
            "index": seg["index"],
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "duration": round(seg["end"] - seg["start"], 3),
            "speaker": seg["speaker"],
            "mapped_ref_speaker": mapped_speaker,
            "audio_name": pathlib.Path(seg.get("audio_name") or seg.get("audio", "")).name,
            "asr_text_chars": len(seg.get("text", "")),
            "gt_overlap_count": len(overlaps),
            "gt_overlap_seconds_sum": round(sum(item["overlap_seconds"] for item in overlaps), 3),
            "gt_text_chars": len(gt_text),
            "matched_speaker_gt_text_chars": len(matched_text),
            "asr_text": seg.get("text", ""),
            "gt_text_by_time_overlap": gt_text,
            "matched_speaker_gt_text_by_time_overlap": matched_text,
        }
        if gt_text:
            metrics = distance_metrics(seg.get("text", ""), gt_text, max_cells=5_000_000)
            row["segment_cer_vs_all_overlap_gt"] = metrics["cer"]
        else:
            row["segment_cer_vs_all_overlap_gt"] = None
        rows.append(row)
    return rows


def write_csv(path, rows):
    if not rows:
        return
    with pathlib.Path(path).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_llm_input(path, segments, include_empty=False):
    lines = []
    for seg in sorted(segments, key=lambda item: (item["start"], item["end"], item["index"])):
        text = normalize_transcript(seg.get("text", ""))
        if not text and not include_empty:
            continue
        lines.append(f"[{seg['index']:04d}][{format_time(seg['start'])}-{format_time(seg['end'])}][{speaker_label(seg['speaker'])}] {text}")
    pathlib.Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Evaluate segment ASR transcript with TextGrid reference.")
    parser.add_argument("--segments", required=True, help="segment_transcripts.json from board_segment_asr_batch.py")
    parser.add_argument("--textgrid", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-distance-cells", type=int, default=80_000_000)
    args = parser.parse_args()

    segments = load_segment_transcripts(args.segments)
    reference = parse_textgrid(args.textgrid)
    pred_labels, ref_labels, matrix = build_overlap_matrix(segments, reference)
    mapping, mapping_overlap = best_label_mapping(pred_labels, ref_labels, matrix)

    asr_all_text = join_text(segments)
    asr_known_text = join_text([row for row in segments if row["speaker"] != "unknown"])
    asr_unknown_text = join_text([row for row in segments if row["speaker"] == "unknown"])
    gt_all_text = join_text(reference)

    gt_seconds = sum(row["end"] - row["start"] for row in reference)
    segment_seconds = sum(row["end"] - row["start"] for row in segments)
    unknown_segments = [row for row in segments if row["speaker"] == "unknown"]
    known_segments = [row for row in segments if row["speaker"] != "unknown"]
    empty_segments = [row for row in segments if not row.get("text")]

    per_segment_rows = segment_gt_rows(segments, reference, mapping)
    unknown_gt_text = normalize_transcript(" ".join(row["gt_text_by_time_overlap"] for row in per_segment_rows if row["speaker"] == "unknown"))

    unknown_seconds = sum(row["end"] - row["start"] for row in unknown_segments)
    unknown_ref_overlap_seconds = sum(row["gt_overlap_seconds_sum"] for row in per_segment_rows if row["speaker"] == "unknown")

    summary = {
        "segments": str(args.segments),
        "textgrid": str(args.textgrid),
        "segment_count": len(segments),
        "known_segment_count": len(known_segments),
        "unknown_segment_count": len(unknown_segments),
        "unknown_segment_ratio": round(len(unknown_segments) / len(segments), 6) if segments else None,
        "empty_text_segment_count": len(empty_segments),
        "asr_text_chars": len(asr_all_text),
        "asr_known_text_chars": len(asr_known_text),
        "asr_unknown_text_chars": len(asr_unknown_text),
        "asr_unknown_text_char_ratio": round(len(asr_unknown_text) / len(asr_all_text), 6) if asr_all_text else None,
        "gt_text_chars": len(gt_all_text),
        "gt_interval_count": len(reference),
        "gt_speech_seconds_sum": round(gt_seconds, 3),
        "segment_seconds_sum": round(segment_seconds, 3),
        "unknown_segment_seconds_sum": round(unknown_seconds, 3),
        "unknown_segment_seconds_ratio": round(unknown_seconds / segment_seconds, 6) if segment_seconds else None,
        "unknown_ref_overlap_seconds_sum": round(unknown_ref_overlap_seconds, 3),
        "unknown_ref_overlap_ratio_of_gt_speech": round(unknown_ref_overlap_seconds / gt_seconds, 6) if gt_seconds else None,
        "mapping_pred_to_ref": mapping,
        "mapping_overlap_seconds": round(mapping_overlap, 3),
        "raw_concat_metrics_all_segments_vs_time_sorted_gt": distance_metrics(asr_all_text, gt_all_text, args.max_distance_cells),
        "raw_concat_metrics_unknown_segments_vs_overlap_gt": distance_metrics(asr_unknown_text, unknown_gt_text, args.max_distance_cells),
        "notes": [
            "Raw concatenation keeps padded segment overlaps, so CER can be worse than the final de-duplicated transcript.",
            "Use llm_input_timeline.txt as the first LLM input candidate; inspect repeated boundary text before final summary.",
        ],
    }

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "asr_text_all.txt").write_text(asr_all_text + "\n", encoding="utf-8")
    (out_dir / "gt_text_time_sorted.txt").write_text(gt_all_text + "\n", encoding="utf-8")
    (out_dir / "unknown_asr_text.txt").write_text(asr_unknown_text + "\n", encoding="utf-8")
    (out_dir / "unknown_gt_overlap_text.txt").write_text(unknown_gt_text + "\n", encoding="utf-8")
    (out_dir / "segment_asr_eval_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "segment_gt_alignment.json").write_text(json.dumps(per_segment_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out_dir / "segment_gt_alignment.csv", per_segment_rows)
    write_llm_input(out_dir / "llm_input_timeline.txt", segments)
    write_llm_input(out_dir / "llm_input_timeline_with_empty.txt", segments, include_empty=True)
    write_gt_timeline(out_dir / "gt_timeline.txt", reference)
    write_mapped_asr_timeline(out_dir / "asr_timeline_mapped.txt", segments, mapping)
    write_mapped_asr_timeline(out_dir / "asr_timeline_mapped_with_empty.txt", segments, mapping, include_empty=True)
    write_segment_overlap_preview(out_dir / "asr_gt_segment_overlap_preview.txt", per_segment_rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote reports to: {out_dir}")
    print(f"- {out_dir / 'segment_asr_eval_summary.json'}")
    print(f"- {out_dir / 'segment_gt_alignment.csv'}")
    print(f"- {out_dir / 'gt_timeline.txt'}")
    print(f"- {out_dir / 'asr_timeline_mapped.txt'}")
    print(f"- {out_dir / 'asr_gt_segment_overlap_preview.txt'}")


if __name__ == "__main__":
    main()
