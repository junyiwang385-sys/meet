#!/usr/bin/env python3
"""Analyze RTTM padding coverage and unknown gap fallback candidates.

This script expands RTTM segments by a padding value, unions their time coverage,
then reports uncovered gaps that would become speaker=unknown fallback segments.
If a TextGrid reference is provided, it also annotates which unknown gaps actually
contain GT speech/text for diagnostic use only.
"""

import argparse
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
            rows.append({"start": start, "end": end, "speaker": parts[7]})
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def parse_textgrid(path):
    if not path:
        return []
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    item_blocks = re.findall(
        r"item \[\d+\]:\s*(.*?)(?=\n\s*item \[\d+\]:|\Z)",
        text,
        flags=re.DOTALL,
    )
    rows = []
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
            if end > start:
                rows.append({"start": start, "end": end, "speaker": speaker, "text": value})
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def wav_duration(path):
    if not path:
        return None
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        return frames / float(rate) if rate else None


def overlap_seconds(left, right):
    return max(0.0, min(left["end"], right["end"]) - max(left["start"], right["start"]))


def apply_padding(rows, pad, audio_duration):
    padded = []
    for row in rows:
        start = max(0.0, row["start"] - pad)
        end = row["end"] + pad
        if audio_duration is not None:
            end = min(audio_duration, end)
        if end > start:
            item = dict(row)
            item["padded_start"] = start
            item["padded_end"] = end
            padded.append(item)
    return padded


def union_intervals(rows):
    spans = sorted((row["padded_start"], row["padded_end"]) for row in rows)
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
            gaps.append({"start": cursor, "end": span["start"]})
        cursor = max(cursor, span["end"])
    if audio_duration is not None and audio_duration - cursor >= min_gap:
        gaps.append({"start": cursor, "end": audio_duration})
    return gaps


def split_gap(gap, max_segment):
    if max_segment <= 0 or gap["end"] - gap["start"] <= max_segment:
        return [gap]
    out = []
    start = gap["start"]
    while start < gap["end"]:
        end = min(gap["end"], start + max_segment)
        out.append({"start": start, "end": end})
        start = end
    return out


def annotate_gap_with_textgrid(gap, ref_rows):
    overlaps = []
    text_chars = 0
    gt_speech_seconds = 0.0
    for ref in ref_rows:
        ov = overlap_seconds(gap, ref)
        if ov <= 0:
            continue
        gt_speech_seconds += ov
        text_chars += len(ref["text"])
        overlaps.append({
            "start": round(ref["start"], 3),
            "end": round(ref["end"], 3),
            "speaker": ref["speaker"],
            "overlap_seconds": round(ov, 3),
            "text": ref["text"],
        })
    return overlaps, gt_speech_seconds, text_chars


def round_row(row):
    out = dict(row)
    out["start"] = round(out["start"], 3)
    out["end"] = round(out["end"], 3)
    out["duration"] = round(out["end"] - out["start"], 3)
    return out


def main():
    parser = argparse.ArgumentParser(description="Analyze unknown fallback gaps after RTTM padding.")
    parser.add_argument("--rttm", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--audio", help="WAV file used to determine full audio duration")
    parser.add_argument("--audio-duration", type=float, help="Full audio duration in seconds; overrides --audio")
    parser.add_argument("--textgrid", help="Optional TextGrid reference for diagnostic annotation")
    parser.add_argument("--pad", type=float, default=1.0, help="Padding seconds applied to RTTM segments")
    parser.add_argument("--min-gap", type=float, default=0.5, help="Only gaps at least this long become unknown candidates")
    parser.add_argument("--max-unknown-segment", type=float, default=20.0, help="Split long unknown gaps into chunks of this length; <=0 disables split")
    args = parser.parse_args()

    rttm_rows = parse_rttm(args.rttm)
    ref_rows = parse_textgrid(args.textgrid) if args.textgrid else []
    duration = args.audio_duration
    if duration is None and args.audio:
        duration = wav_duration(args.audio)
    if duration is None:
        ends = [row["end"] for row in rttm_rows]
        ends.extend(row["end"] for row in ref_rows)
        duration = max(ends) if ends else 0.0

    padded = apply_padding(rttm_rows, args.pad, duration)
    coverage = union_intervals(padded)
    raw_gaps = gaps_from_coverage(coverage, duration, args.min_gap)

    unknown_segments = []
    for gap in raw_gaps:
        for part in split_gap(gap, args.max_unknown_segment):
            item = round_row(part)
            item["speaker"] = "unknown"
            item["source"] = "gap_fallback"
            if ref_rows:
                overlaps, gt_speech_seconds, text_chars = annotate_gap_with_textgrid(part, ref_rows)
                item["gt_speech_seconds"] = round(gt_speech_seconds, 3)
                item["gt_text_chars"] = text_chars
                item["gt_overlaps"] = overlaps
            unknown_segments.append(item)

    total_unknown_seconds = sum(item["duration"] for item in unknown_segments)
    total_covered_seconds = sum(span["end"] - span["start"] for span in coverage)
    total_gt_speech_in_unknown = sum(item.get("gt_speech_seconds", 0.0) for item in unknown_segments)
    total_gt_chars_in_unknown = sum(item.get("gt_text_chars", 0) for item in unknown_segments)
    unknown_with_gt = [item for item in unknown_segments if item.get("gt_speech_seconds", 0.0) > 0]
    unknown_without_gt = [item for item in unknown_segments if item.get("gt_speech_seconds", 0.0) <= 0]

    summary = {
        "rttm": str(args.rttm),
        "audio": str(args.audio) if args.audio else None,
        "textgrid": str(args.textgrid) if args.textgrid else None,
        "audio_duration_seconds": round(duration, 3),
        "pad_seconds": args.pad,
        "min_gap_seconds": args.min_gap,
        "max_unknown_segment_seconds": args.max_unknown_segment,
        "rttm_segments": len(rttm_rows),
        "coverage_spans_after_padding": len(coverage),
        "covered_seconds_after_padding_union": round(total_covered_seconds, 3),
        "covered_ratio_after_padding_union": round(total_covered_seconds / duration, 6) if duration else None,
        "raw_gap_count": len(raw_gaps),
        "unknown_segment_count_after_split": len(unknown_segments),
        "unknown_seconds_after_split": round(total_unknown_seconds, 3),
        "unknown_ratio_after_split": round(total_unknown_seconds / duration, 6) if duration else None,
        "unknown_segments_with_gt_speech": len(unknown_with_gt),
        "unknown_segments_without_gt_speech": len(unknown_without_gt),
        "gt_speech_seconds_inside_unknown": round(total_gt_speech_in_unknown, 3),
        "gt_text_chars_inside_unknown": total_gt_chars_in_unknown,
        "top_unknown_with_gt": sorted(
            [item for item in unknown_segments if item.get("gt_speech_seconds", 0.0) > 0],
            key=lambda item: item.get("gt_speech_seconds", 0.0),
            reverse=True,
        )[:20],
        "top_long_unknown": sorted(unknown_segments, key=lambda item: item["duration"], reverse=True)[:20],
    }

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gap_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "unknown_segments.json").write_text(json.dumps(unknown_segments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (out_dir / "unknown_segments.txt").open("w", encoding="utf-8") as fh:
        for item in unknown_segments:
            extra = ""
            if "gt_speech_seconds" in item:
                extra = f" gt_speech={item['gt_speech_seconds']:.3f}s gt_chars={item['gt_text_chars']}"
            fh.write(f"[{item['start']:.3f}-{item['end']:.3f}] dur={item['duration']:.3f}s speaker=unknown{extra}\n")
            for ov in item.get("gt_overlaps", [])[:5]:
                fh.write(f"  GT [{ov['start']:.3f}-{ov['end']:.3f}] {ov['speaker']}: {ov['text']}\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote reports to: {out_dir}")
    print(f"- {out_dir / 'gap_summary.json'}")
    print(f"- {out_dir / 'unknown_segments.json'}")
    print(f"- {out_dir / 'unknown_segments.txt'}")


if __name__ == "__main__":
    main()
