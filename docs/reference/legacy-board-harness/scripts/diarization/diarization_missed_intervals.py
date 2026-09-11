#!/usr/bin/env python3
"""Export TextGrid speech intervals missed by diarization RTTM.

This is a diagnostic script for speaker diarization coverage. It treats TextGrid
non-empty intervals as reference speech and RTTM segments as predicted speech,
then reports TextGrid intervals whose overlap with RTTM is below a threshold.
"""

import argparse
import csv
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
            if end <= start:
                continue
            rows.append({"start": start, "end": end, "speaker": speaker, "text": value})
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def parse_rttm(path, pad=0.0, audio_end=None):
    rows = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8 or parts[0] != "SPEAKER":
            continue
        start = float(parts[3]) - pad
        end = float(parts[3]) + float(parts[4]) + pad
        start = max(0.0, start)
        if audio_end is not None:
            end = min(audio_end, end)
        if end <= start:
            continue
        rows.append({"start": start, "end": end, "speaker": parts[7]})
    return sorted(rows, key=lambda item: (item["start"], item["end"], item["speaker"]))


def overlap_seconds(a, b):
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def total_overlap(ref, pred_rows):
    total = 0.0
    speakers = {}
    for pred in pred_rows:
        ov = overlap_seconds(ref, pred)
        if ov <= 0:
            continue
        total += ov
        speakers[pred["speaker"]] = speakers.get(pred["speaker"], 0.0) + ov
    return min(total, ref["end"] - ref["start"]), speakers


def seconds(value):
    return round(float(value), 3)


def text_preview(text, limit=80):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def main():
    parser = argparse.ArgumentParser(description="Find TextGrid reference intervals missed by RTTM diarization output.")
    parser.add_argument("--rttm", required=True, help="Diarization RTTM file")
    parser.add_argument("--textgrid", required=True, help="Reference TextGrid file")
    parser.add_argument("--out-dir", required=True, help="Directory for missed interval reports")
    parser.add_argument("--coverage-threshold", type=float, default=0.5, help="Reference interval is missed if overlap/ref_duration is below this value")
    parser.add_argument("--rttm-pad", type=float, default=0.0, help="Pad each RTTM segment by N seconds before comparing")
    parser.add_argument("--long-threshold", type=float, default=2.0, help="Duration threshold for long missed intervals")
    args = parser.parse_args()

    ref_rows = parse_textgrid(args.textgrid)
    audio_end = max((row["end"] for row in ref_rows), default=None)
    pred_rows = parse_rttm(args.rttm, pad=args.rttm_pad, audio_end=audio_end)

    missed = []
    partial = []
    covered = []

    for ref in ref_rows:
        duration = ref["end"] - ref["start"]
        overlap, speaker_overlaps = total_overlap(ref, pred_rows)
        coverage = overlap / duration if duration > 0 else 0.0
        best_pred_speaker = None
        best_pred_overlap = 0.0
        if speaker_overlaps:
            best_pred_speaker, best_pred_overlap = max(speaker_overlaps.items(), key=lambda item: item[1])
        item = {
            "start": seconds(ref["start"]),
            "end": seconds(ref["end"]),
            "duration": seconds(duration),
            "ref_speaker": ref["speaker"],
            "text": ref["text"],
            "text_chars": len(ref["text"]),
            "overlap_seconds": seconds(overlap),
            "coverage": round(coverage, 6),
            "best_pred_speaker": best_pred_speaker,
            "best_pred_overlap_seconds": seconds(best_pred_overlap),
        }
        if coverage < args.coverage_threshold:
            missed.append(item)
        elif coverage < 0.95:
            partial.append(item)
        else:
            covered.append(item)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def write_json(name, obj):
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_txt(name, rows):
        with (out_dir / name).open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(
                    f"[{row['start']:.3f}-{row['end']:.3f}] "
                    f"dur={row['duration']:.3f}s cov={row['coverage']:.3f} "
                    f"ref={row['ref_speaker']} pred={row['best_pred_speaker']} "
                    f"chars={row['text_chars']} text={row['text']}\n"
                )

    def write_csv(name, rows):
        fields = [
            "start", "end", "duration", "ref_speaker", "coverage", "overlap_seconds",
            "best_pred_speaker", "best_pred_overlap_seconds", "text_chars", "text",
        ]
        with (out_dir / name).open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fields})

    total_ref_seconds = sum(row["end"] - row["start"] for row in ref_rows)
    missed_seconds = sum(row["duration"] for row in missed)
    partial_seconds = sum(row["duration"] for row in partial)
    missed_chars = sum(row["text_chars"] for row in missed)
    long_missed = [row for row in missed if row["duration"] >= args.long_threshold]
    long_missed_chars = sum(row["text_chars"] for row in long_missed)

    summary = {
        "rttm": str(args.rttm),
        "textgrid": str(args.textgrid),
        "coverage_threshold": args.coverage_threshold,
        "rttm_pad_seconds": args.rttm_pad,
        "ref_intervals": len(ref_rows),
        "pred_segments": len(pred_rows),
        "total_ref_speech_seconds": seconds(total_ref_seconds),
        "covered_intervals": len(covered),
        "partial_intervals": len(partial),
        "missed_intervals": len(missed),
        "missed_seconds": seconds(missed_seconds),
        "missed_seconds_ratio": round(missed_seconds / total_ref_seconds, 6) if total_ref_seconds else None,
        "partial_seconds": seconds(partial_seconds),
        "missed_text_chars": missed_chars,
        "long_threshold_seconds": args.long_threshold,
        "long_missed_intervals": len(long_missed),
        "long_missed_seconds": seconds(sum(row["duration"] for row in long_missed)),
        "long_missed_text_chars": long_missed_chars,
        "top_long_missed_preview": [
            {
                "start": row["start"],
                "end": row["end"],
                "duration": row["duration"],
                "ref_speaker": row["ref_speaker"],
                "coverage": row["coverage"],
                "text": text_preview(row["text"]),
            }
            for row in sorted(long_missed, key=lambda item: item["duration"], reverse=True)[:30]
        ],
    }

    write_json("missed_summary.json", summary)
    write_json("missed_intervals.json", missed)
    write_json("partial_intervals.json", partial)
    write_txt("missed_intervals.txt", missed)
    write_txt("long_missed_intervals.txt", sorted(long_missed, key=lambda item: item["duration"], reverse=True))
    write_csv("missed_intervals.csv", missed)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote reports to: {out_dir}")
    print(f"- {out_dir / 'missed_summary.json'}")
    print(f"- {out_dir / 'missed_intervals.txt'}")
    print(f"- {out_dir / 'long_missed_intervals.txt'}")


if __name__ == "__main__":
    main()
