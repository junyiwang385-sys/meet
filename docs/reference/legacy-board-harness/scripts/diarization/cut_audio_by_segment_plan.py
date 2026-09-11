#!/usr/bin/env python3
"""Cut a WAV file into ASR segments from segment_plan.json/csv.

The input WAV is expected to be the normalized working audio used by diarization,
for example mono 16 kHz 16-bit PCM WAV. The script writes one WAV per segment and
reports storage usage before and after cutting.
"""

import argparse
import csv
import json
import pathlib
import wave


def human_size(num_bytes):
    value = float(num_bytes)
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if value < 1024.0 or unit == "TiB":
            return f"{value:.2f} {unit}"
        value /= 1024.0


def load_segments(path):
    path = pathlib.Path(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    else:
        raise ValueError(f"Unsupported segment plan format: {path}")

    segments = []
    for index, row in enumerate(rows):
        start = float(row["start"])
        end = float(row["end"])
        if end <= start:
            continue
        segments.append({
            "index": int(row.get("index", index)),
            "start": start,
            "end": end,
            "duration": end - start,
            "speaker": str(row.get("speaker", "unknown")),
            "source": str(row.get("source", "segment_plan")),
        })
    return sorted(segments, key=lambda item: item["index"])


def safe_speaker_name(value):
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value)


def cut_segments(audio_path, segments, out_audio_dir, min_duration=0.05):
    out_audio_dir.mkdir(parents=True, exist_ok=True)
    written = []

    with wave.open(str(audio_path), "rb") as src:
        params = src.getparams()
        sample_rate = src.getframerate()
        total_frames = src.getnframes()
        duration = total_frames / float(sample_rate)

        for seg in segments:
            start = max(0.0, min(seg["start"], duration))
            end = max(0.0, min(seg["end"], duration))
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
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Cut WAV audio by segment_plan.json/csv and report storage usage.")
    parser.add_argument("--audio", required=True, help="Working WAV to cut, usually mono 16k 16-bit PCM")
    parser.add_argument("--segment-plan", required=True, help="segment_plan.json or segment_plan.csv")
    parser.add_argument("--out-dir", required=True, help="Output directory for wav segments and reports")
    parser.add_argument("--source-audio", help="Optional original source audio, such as the original FLAC, for storage comparison")
    parser.add_argument("--min-duration", type=float, default=0.05, help="Skip segments shorter than this many seconds")
    args = parser.parse_args()

    audio_path = pathlib.Path(args.audio)
    plan_path = pathlib.Path(args.segment_plan)
    out_dir = pathlib.Path(args.out_dir)
    out_audio_dir = out_dir / "wav_segments"
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = load_segments(plan_path)
    written = cut_segments(audio_path, segments, out_audio_dir, args.min_duration)

    source_size = pathlib.Path(args.source_audio).stat().st_size if args.source_audio else None
    input_wav_size = audio_path.stat().st_size
    output_size = sum(item["size_bytes"] for item in written)
    known_items = [item for item in written if item["speaker"] != "unknown"]
    unknown_items = [item for item in written if item["speaker"] == "unknown"]

    summary = {
        "source_audio": str(args.source_audio) if args.source_audio else None,
        "source_audio_size_bytes": source_size,
        "source_audio_size_human": human_size(source_size) if source_size is not None else None,
        "input_wav": str(audio_path),
        "input_wav_size_bytes": input_wav_size,
        "input_wav_size_human": human_size(input_wav_size),
        "segment_plan": str(plan_path),
        "out_audio_dir": str(out_audio_dir),
        "segment_count_in_plan": len(segments),
        "segment_count_written": len(written),
        "known_segment_count_written": len(known_items),
        "unknown_segment_count_written": len(unknown_items),
        "known_seconds_sum": round(sum(item["duration"] for item in known_items), 3),
        "unknown_seconds_sum": round(sum(item["duration"] for item in unknown_items), 3),
        "output_segments_size_bytes": output_size,
        "output_segments_size_human": human_size(output_size),
        "output_vs_input_wav_ratio": round(output_size / input_wav_size, 6) if input_wav_size else None,
        "board_storage_if_keep_source_and_segments_bytes": (source_size or 0) + output_size,
        "board_storage_if_keep_source_and_segments_human": human_size((source_size or 0) + output_size),
        "board_storage_if_keep_input_wav_and_segments_bytes": input_wav_size + output_size,
        "board_storage_if_keep_input_wav_and_segments_human": human_size(input_wav_size + output_size),
    }

    (out_dir / "cut_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "cut_segments.json").write_text(json.dumps(written, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out_dir / "cut_segments.csv", written)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote reports to: {out_dir}")
    print(f"- {out_dir / 'cut_summary.json'}")
    print(f"- {out_dir / 'cut_segments.csv'}")
    print(f"- {out_audio_dir}")


if __name__ == "__main__":
    main()
