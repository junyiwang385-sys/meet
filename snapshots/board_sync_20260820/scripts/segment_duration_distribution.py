#!/usr/bin/env python3
"""Summarize diarization/ASR segment duration distribution by speaker."""

import argparse
import csv
import json
import pathlib


BINS = [
    ("<1s", 0.0, 1.0),
    ("1-2s", 1.0, 2.0),
    ("2-5s", 2.0, 5.0),
    ("5-10s", 5.0, 10.0),
    ("10-20s", 10.0, 20.0),
    ("20-30s", 20.0, 30.0),
    (">=30s", 30.0, None),
]


def load_rows(path):
    path = pathlib.Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        with path.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))

    out = []
    for row in rows:
        start = float(row["start"])
        end = float(row["end"])
        duration = float(row.get("duration") or end - start)
        if duration <= 0:
            continue
        out.append({"speaker": str(row.get("speaker", "unknown")), "duration": duration})
    return out


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * fraction
    lower = int(pos)
    upper = min(lower + 1, len(values) - 1)
    weight = pos - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def summarize(values):
    bins = {}
    for label, low, high in BINS:
        bins[label] = sum(1 for value in values if value >= low and (high is None or value < high))
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


def main():
    parser = argparse.ArgumentParser(description="Show segment duration distribution by speaker.")
    parser.add_argument("--input", required=True, help="cut_segments.csv, segment_plan.csv, or segment JSON")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    rows = load_rows(args.input)
    groups = {
        "all": [row["duration"] for row in rows],
        "known": [row["duration"] for row in rows if row["speaker"] != "unknown"],
        "unknown": [row["duration"] for row in rows if row["speaker"] == "unknown"],
    }
    for speaker in sorted({row["speaker"] for row in rows}):
        groups[f"speaker:{speaker}"] = [row["duration"] for row in rows if row["speaker"] == speaker]

    result = {name: summarize(values) for name, values in groups.items() if values}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        pathlib.Path(args.output).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
