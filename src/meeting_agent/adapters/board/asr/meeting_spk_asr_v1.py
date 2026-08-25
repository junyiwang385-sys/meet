#!/usr/bin/env python3
"""Board-side V1: speaker diarization segments -> Qwen3-ASR -> speaker transcript.

This script is intentionally standard-library only so it can be copied to the
RK1828 board. It does not run speaker diarization itself; it consumes the
post-processed diarization output produced by the CAM++ pipeline, cuts WAV
chunks, runs Qwen3-ASR for each selected chunk, and writes speaker-attributed
transcript JSON/TXT.

Recommended V1 input is the postprocessed file:
  /userdata/meeting_agent/output/spk_diarization/L_R004S06C01_spk_segments_win3_thr068_main_unknown.json

Default ASR policy:
  - include main speakers
  - include unknown_boundary
  - skip unknown_fragment unless explicitly requested
  - merge adjacent same-speaker segments before ASR chunking
  - allow short unknown_fragment bridges between same-speaker segments
  - split long merged turns to <= 30s chunks for ASR
  - avoid tiny trailing ASR chunks where possible
  - add 0.3s audio padding on both sides while keeping original timestamps
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_AUDIO = "/userdata/meeting_agent/input/L_R004S06C01_full_16k.wav"
DEFAULT_DIARIZATION = "/userdata/meeting_agent/output/spk_diarization/L_R004S06C01_spk_segments_win3_thr068_main_unknown.json"
DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/asr_spk_v1"
DEFAULT_ASR_DEMO_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo"
DEFAULT_ASR_MODEL_DIR = "/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn"


class V1Error(RuntimeError):
    pass


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise V1Error(f"{label} not found: {path}")


def require_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise V1Error(f"{label} not found: {path}")


def require_executable(path: Path, label: str) -> None:
    require_file(path, label)
    if not os.access(path, os.X_OK):
        raise V1Error(f"{label} is not executable: {path}")


def fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total = int(seconds)
    ms = int(round((seconds - total) * 1000))
    if ms == 1000:
        total += 1
        ms = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_") or "x"


def speaker_kind(speaker: str) -> str:
    if speaker == "unknown_boundary":
        return "boundary"
    if speaker == "unknown_fragment":
        return "fragment"
    if speaker.startswith("speaker_"):
        return "main"
    return "unknown"


def strip_ansi_and_tags(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"<\|[^|]+\|>", "", text)
    return text


def looks_like_transcript(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    lower = s.lower()
    reject_words = [
        "rknn", "rknnapi", "model", "init", "load", "elapsed", "rtf", "time",
        "ms", "fps", "input", "output", "version", "usage", "warning", "error",
        "encoder", "token", "tokenizer", "vocab", "special_", "bos", "eos", "eog",
        "audio", "wav", "path", "device", "commit", "final", "llama", "tensor",
        "infer", "malloc", "free", "shape", "dtype", "core", "server", "errno",
    ]
    if any(w in lower for w in reject_words) and not re.search(r"[一-鿿]", s):
        return False
    if re.match(r"^[\[\(]?[IEWDF]\s", s):
        return False
    if re.search(r"[一-鿿]", s):
        return True
    letters = re.findall(r"[A-Za-z]", s)
    return len(letters) >= 8 and len(s) >= 12


def clean_candidate(line: str) -> str:
    s = strip_ansi_and_tags(line).strip()
    s = re.sub(r"^(?:result|asr result|recognition result|final result|final commit result)\s*[:：]\s*", "", s, flags=re.I)
    s = s.strip(" \t\n\r\"'")
    return s.strip()


def parse_qwen3_asr_output(raw_text: str) -> str:
    """Parse Qwen3-ASR demo stdout and return transcript text."""
    text = strip_ansi_and_tags(raw_text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    block_markers = [
        r"^text\s+res\s*[:：]\s*(.*)$",
        r"^Final\s+Commit\s+Result\s*[:：]\s*(.*)$",
    ]
    stop_patterns = [
        r"^-{5,}",
        r"^LLM\s+part\s+performance",
        r"^Stage\s+Total\s+Time",
        r"^Audio\s+latency",
        r"^Audio\s+Duration",
        r"^Total\s+Inference",
        r"^RTF\s*=",
        r"^TTFT\s+",
        r"^-->",
    ]
    for idx, line in enumerate(lines):
        matched = False
        first = ""
        for pat in block_markers:
            m = re.search(pat, line, flags=re.I)
            if m:
                matched = True
                first = clean_candidate(m.group(1))
                break
        if not matched:
            continue
        collected: List[str] = []
        if first:
            collected.append(first)
        for next_line in lines[idx + 1:]:
            if any(re.search(pat, next_line, flags=re.I) for pat in stop_patterns):
                break
            candidate = clean_candidate(next_line)
            if candidate and looks_like_transcript(candidate):
                collected.append(candidate)
        if collected:
            return "\n".join(collected).strip()

    marker_patterns = [
        r"Final\s+Result\s*[:：]\s*(.*)",
        r"ASR\s+Result\s*[:：]\s*(.*)",
        r"Recognition\s+Result\s*[:：]\s*(.*)",
        r"Result\s*[:：]\s*(.*)",
    ]
    for idx, line in enumerate(lines):
        for pat in marker_patterns:
            m = re.search(pat, line, flags=re.I)
            if not m:
                continue
            candidate = clean_candidate(m.group(1))
            if candidate and looks_like_transcript(candidate):
                return candidate
            if idx + 1 < len(lines):
                candidate = clean_candidate(lines[idx + 1])
                if candidate and looks_like_transcript(candidate):
                    return candidate
    return ""


def get_wav_info(path: Path) -> Dict[str, Any]:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        duration = frame_count / float(sample_rate)
    return {
        "channels": channels,
        "sample_width": sample_width,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "duration": duration,
    }


def cut_wav(src: Path, dst: Path, start: float, end: float) -> Dict[str, Any]:
    if end <= start:
        raise V1Error(f"invalid cut range: {start}-{end}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(src), "rb") as inp:
        params = inp.getparams()
        rate = inp.getframerate()
        total_frames = inp.getnframes()
        start_frame = max(0, int(round(start * rate)))
        end_frame = min(total_frames, int(round(end * rate)))
        if end_frame <= start_frame:
            raise V1Error(f"empty cut after frame clamp: {start}-{end}")
        inp.setpos(start_frame)
        data = inp.readframes(end_frame - start_frame)
    with wave.open(str(dst), "wb") as out:
        out.setparams(params)
        out.writeframes(data)
    return {
        "cut_start": start_frame / float(rate),
        "cut_end": end_frame / float(rate),
        "cut_duration": (end_frame - start_frame) / float(rate),
        "sample_rate": rate,
        "frames": end_frame - start_frame,
    }


def load_diarization(path: Path) -> List[Dict[str, Any]]:
    require_file(path, "diarization file")
    if path.suffix.lower() == ".json":
        data = json.loads(read_text(path))
        raw_segments = data.get("segments", data if isinstance(data, list) else [])
        if not isinstance(raw_segments, list):
            raise V1Error(f"JSON diarization has no segments list: {path}")
        segments: List[Dict[str, Any]] = []
        for i, x in enumerate(raw_segments, 1):
            start = float(x["start"])
            end = float(x["end"])
            spk = str(x.get("speaker") or x.get("label") or x.get("raw_speaker") or "unknown")
            if end <= start:
                continue
            segments.append({
                "id": int(x.get("id", i)) if str(x.get("id", i)).isdigit() else i,
                "start": start,
                "end": end,
                "duration": end - start,
                "speaker": spk,
                "speaker_kind": str(x.get("speaker_kind") or speaker_kind(spk)),
                "raw_speakers": x.get("raw_speakers", []),
                "reasons": x.get("reasons", []),
                "source": "json",
            })
        return sorted(segments, key=lambda x: (x["start"], x["end"]))

    # Postprocess TXT format:
    # 0003 [10.72-52.72] speaker_4 dur=42.00s raw=speaker_4 reason=main
    txt_re = re.compile(
        r"^\s*(\d+)\s+\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s+(\S+)"
        r"(?:\s+dur=(\d+(?:\.\d+)?)s)?(?:\s+raw=([^\s]+))?(?:\s+reason=([^\s]+))?"
    )
    segments = []
    for line in read_text(path).splitlines():
        m = txt_re.search(line)
        if not m:
            continue
        start = float(m.group(2))
        end = float(m.group(3))
        spk = m.group(4)
        if end <= start:
            continue
        raw = m.group(6) or ""
        reason = m.group(7) or ""
        segments.append({
            "id": int(m.group(1)),
            "start": start,
            "end": end,
            "duration": end - start,
            "speaker": spk,
            "speaker_kind": speaker_kind(spk),
            "raw_speakers": [x for x in raw.split(",") if x],
            "reasons": [x for x in reason.split(",") if x],
            "source": "txt",
        })
    return sorted(segments, key=lambda x: (x["start"], x["end"]))


def should_include_segment(seg: Dict[str, Any], args: argparse.Namespace) -> bool:
    kind = seg.get("speaker_kind") or speaker_kind(seg["speaker"])
    dur = float(seg["end"] - seg["start"])
    if kind == "main":
        return dur >= args.min_asr_sec
    if seg["speaker"] == "unknown_boundary":
        return (not args.skip_boundary) and dur >= args.min_boundary_sec
    if seg["speaker"] == "unknown_fragment":
        return args.include_fragments and dur >= args.min_fragment_sec
    return args.include_unknown and dur >= args.min_asr_sec


def unique_keep_order(values: Iterable[Any]) -> List[Any]:
    seen = set()
    result = []
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def segment_to_asr_unit(seg: Dict[str, Any], unit_id: int) -> Dict[str, Any]:
    return {
        "unit_id": unit_id,
        "id": seg.get("id"),
        "source_segment_id": seg.get("id"),
        "source_segment_ids": [seg.get("id")],
        "start": float(seg["start"]),
        "end": float(seg["end"]),
        "duration": float(seg["end"] - seg["start"]),
        "speaker": seg["speaker"],
        "speaker_kind": seg.get("speaker_kind") or speaker_kind(seg["speaker"]),
        "raw_speakers": list(seg.get("raw_speakers", [])),
        "reasons": list(seg.get("reasons", [])),
        "bridged_unknown_fragment_ids": [],
        "merged_segment_count": 1,
    }


def merge_unit_with_segment(unit: Dict[str, Any], seg: Dict[str, Any], bridge: Optional[List[Dict[str, Any]]] = None) -> None:
    bridge = bridge or []
    source_ids = list(unit.get("source_segment_ids", []))
    source_ids.extend(x.get("id") for x in bridge)
    source_ids.append(seg.get("id"))
    unit["source_segment_ids"] = [x for x in unique_keep_order(source_ids) if x is not None]
    unit["bridged_unknown_fragment_ids"] = [
        x for x in unique_keep_order(list(unit.get("bridged_unknown_fragment_ids", [])) + [b.get("id") for b in bridge])
        if x is not None
    ]
    unit["end"] = float(seg["end"])
    unit["duration"] = float(unit["end"] - unit["start"])
    unit["raw_speakers"] = unique_keep_order(
        list(unit.get("raw_speakers", []))
        + [r for b in bridge for r in b.get("raw_speakers", [])]
        + list(seg.get("raw_speakers", []))
    )
    unit["reasons"] = unique_keep_order(
        list(unit.get("reasons", []))
        + [r for b in bridge for r in b.get("reasons", [])]
        + list(seg.get("reasons", []))
    )
    unit["merged_segment_count"] = len(unit["source_segment_ids"])


def build_asr_units(segments: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    """Merge diarization segments into ASR-friendly same-speaker units.

    Diarization segments optimize speaker labels and may be very short. ASR units
    optimize transcription context while preserving speaker-boundary safety:
      - merge only same main speaker segments;
      - allow small gaps between them;
      - optionally bridge very short unknown_fragment islands;
      - never cross unknown_boundary or a different main speaker.
    """
    if not args.merge_same_speaker:
        return [segment_to_asr_unit(seg, i + 1) for i, seg in enumerate(segments) if should_include_segment(seg, args)]

    units: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    pending_bridge: List[Dict[str, Any]] = []

    def flush_current() -> None:
        nonlocal current, pending_bridge
        if current is not None:
            current["unit_id"] = len(units) + 1
            units.append(current)
        current = None
        pending_bridge = []

    for seg in segments:
        kind = seg.get("speaker_kind") or speaker_kind(seg["speaker"])
        dur = float(seg["end"] - seg["start"])

        if kind == "fragment" and not args.include_fragments:
            if (
                current is not None
                and current.get("speaker_kind") == "main"
                and dur <= args.bridge_fragment_sec
                and float(seg["start"]) - float(current["end"]) <= args.merge_gap_sec
            ):
                pending_bridge = [seg]
            else:
                flush_current()
            continue

        if not should_include_segment(seg, args):
            flush_current()
            continue

        if kind == "main":
            if current is None:
                current = segment_to_asr_unit(seg, len(units) + 1)
                pending_bridge = []
                continue

            if current.get("speaker_kind") == "main" and current.get("speaker") == seg["speaker"]:
                if pending_bridge:
                    bridge_end = float(pending_bridge[-1]["end"])
                    if float(seg["start"]) - bridge_end <= args.merge_gap_sec:
                        merge_unit_with_segment(current, seg, pending_bridge)
                        pending_bridge = []
                        continue
                elif float(seg["start"]) - float(current["end"]) <= args.merge_gap_sec:
                    merge_unit_with_segment(current, seg)
                    continue

            flush_current()
            current = segment_to_asr_unit(seg, len(units) + 1)
            pending_bridge = []
            continue

        flush_current()
        units.append(segment_to_asr_unit(seg, len(units) + 1))

    flush_current()
    for i, unit in enumerate(units, 1):
        unit["unit_id"] = i
    return units


def split_segment_for_asr(seg: Dict[str, Any], max_sec: float, min_sec: float, min_target_sec: float) -> List[Dict[str, Any]]:
    start = float(seg["start"])
    end = float(seg["end"])
    if end <= start:
        return []

    total = end - start
    if total <= max_sec:
        pieces = [(start, end, 1)]
    else:
        pieces = []
        cur = start
        part = 1
        while end - cur > max_sec:
            remaining_after = end - (cur + max_sec)
            if 0 < remaining_after < min_target_sec and pieces:
                break
            pieces.append((cur, cur + max_sec, part))
            cur += max_sec
            part += 1
        if end - cur >= min_sec or not pieces:
            pieces.append((cur, end, part))
        elif pieces:
            # Avoid a tiny trailing chunk: extend previous chunk to the real end.
            s0, _e0, p0 = pieces[-1]
            pieces[-1] = (s0, end, p0)

        if len(pieces) >= 2 and pieces[-1][1] - pieces[-1][0] < min_target_sec:
            s_last, e_last, _p_last = pieces.pop()
            s_prev, _e_prev, p_prev = pieces[-1]
            pieces[-1] = (s_prev, e_last, p_prev)

    result = []
    for s, e, p in pieces:
        x = dict(seg)
        x["chunk_start"] = s
        x["chunk_end"] = e
        x["chunk_duration"] = e - s
        x["part"] = p
        x["source_segment_id"] = seg.get("source_segment_id") or seg.get("id")
        x["source_segment_ids"] = list(seg.get("source_segment_ids", [x["source_segment_id"]]))
        result.append(x)
    return result


def build_asr_command(args: argparse.Namespace, audio_file: Path) -> Tuple[List[str], Path]:
    demo_dir = Path(args.asr_demo_dir)
    model_dir = Path(args.asr_model_dir)
    require_dir(demo_dir, "ASR demo dir")
    require_dir(model_dir, "ASR model dir")

    if args.asr_mode == "offline":
        binary = demo_dir / "rknn_qwen3_asr_demo"
        model_files = [
            model_dir / "encoder.rknn",
            model_dir / "encoder.weight",
            model_dir / "llm.rknn",
            model_dir / "llm.weight",
            model_dir / "llm.tokenizer.gguf",
            model_dir / "llm.embed.bin",
        ]
    else:
        binary = demo_dir / "rknn_qwen3_asr_demo_online"
        model_files = [
            model_dir / "encoder_online.rknn",
            model_dir / "encoder_online.weight",
            model_dir / "llm.rknn",
            model_dir / "llm.weight",
            model_dir / "llm.tokenizer.gguf",
            model_dir / "llm.embed.bin",
        ]

    require_executable(binary, "ASR binary")
    for p in model_files:
        require_file(p, f"ASR model file {p.name}")

    cmd = [str(binary)] + [str(p) for p in model_files] + [
        args.asr_encoder_device,
        args.asr_llm_device,
        str(audio_file),
    ]
    if args.asr_mode == "online" and args.asr_stream:
        cmd.append("-s")
    return cmd, demo_dir


def run_qwen3_asr(args: argparse.Namespace, wav_path: Path, raw_log: Path) -> Dict[str, Any]:
    cmd, demo_dir = build_asr_command(args, wav_path)
    env = os.environ.copy()
    lib_dir = str(demo_dir / "lib")
    env["LD_LIBRARY_PATH"] = lib_dir + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")

    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(demo_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        timeout=args.asr_timeout,
        check=False,
    )
    elapsed = time.time() - started
    raw = proc.stdout or ""
    write_text(raw_log, raw)
    transcript = parse_qwen3_asr_output(raw) if proc.returncode == 0 else ""
    status = "ok" if proc.returncode == 0 and transcript.strip() else "parse_empty"
    if proc.returncode != 0:
        status = "asr_failed"
    return {
        "status": status,
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "transcript": transcript.strip(),
        "raw_log": str(raw_log),
        "cmd": cmd,
    }


def make_asr_plan(segments: List[Dict[str, Any]], args: argparse.Namespace, audio_duration: float) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    units = build_asr_units(segments, args)
    jobs: List[Dict[str, Any]] = []
    for unit in units:
        for piece in split_segment_for_asr(unit, args.max_asr_sec, args.min_asr_sec, args.min_target_asr_sec):
            idx = len(jobs) + 1
            start = float(piece["chunk_start"])
            end = float(piece["chunk_end"])
            cut_start = max(0.0, start - args.pad_sec)
            cut_end = min(audio_duration, end + args.pad_sec)
            name = f"chunk_{idx:04d}_{start:08.2f}_{end:08.2f}_{safe_name(piece['speaker'])}.wav"
            job = {
                "id": idx,
                "source_unit_id": piece.get("unit_id"),
                "source_segment_id": piece.get("source_segment_id"),
                "source_segment_ids": piece.get("source_segment_ids", []),
                "merged_segment_count": piece.get("merged_segment_count", 1),
                "bridged_unknown_fragment_ids": piece.get("bridged_unknown_fragment_ids", []),
                "part": piece.get("part", 1),
                "start": start,
                "end": end,
                "duration": end - start,
                "cut_start": cut_start,
                "cut_end": cut_end,
                "cut_duration": cut_end - cut_start,
                "speaker": piece["speaker"],
                "speaker_kind": piece.get("speaker_kind") or speaker_kind(piece["speaker"]),
                "raw_speakers": piece.get("raw_speakers", []),
                "reasons": piece.get("reasons", []),
                "wav_name": name,
            }
            jobs.append(job)
    if args.limit and args.limit > 0:
        jobs = jobs[: args.limit]
        used_unit_ids = {job.get("source_unit_id") for job in jobs}
        units = [unit for unit in units if unit.get("unit_id") in used_unit_ids]
        for i, job in enumerate(jobs, 1):
            job["id"] = i
    return jobs, units


def build_turns(chunks: List[Dict[str, Any]], merge_gap: float) -> List[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = []
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        if (
            turns
            and turns[-1]["speaker"] == chunk["speaker"]
            and chunk["start"] - turns[-1]["end"] <= merge_gap
        ):
            turns[-1]["end"] = chunk["end"]
            turns[-1]["texts"].append(text)
            turns[-1]["chunk_ids"].append(chunk["id"])
            turns[-1]["text"] = "".join(turns[-1]["texts"])
        else:
            turns.append({
                "id": len(turns) + 1,
                "start": chunk["start"],
                "end": chunk["end"],
                "speaker": chunk["speaker"],
                "speaker_kind": chunk.get("speaker_kind") or speaker_kind(chunk["speaker"]),
                "texts": [text],
                "text": text,
                "chunk_ids": [chunk["id"]],
            })
    return turns


def transcript_lines(items: Iterable[Dict[str, Any]]) -> List[str]:
    lines = []
    for x in items:
        text = (x.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{fmt_ts(float(x['start']))}-{fmt_ts(float(x['end']))}] {x['speaker']}: {text}")
    return lines


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="V1 speaker diarization -> Qwen3-ASR speaker transcript on RK1828 board")
    parser.add_argument("--audio-file", default=DEFAULT_AUDIO)
    parser.add_argument("--diarization-file", default=DEFAULT_DIARIZATION, help="Postprocessed diarization JSON/TXT")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)

    parser.add_argument("--asr-demo-dir", default=DEFAULT_ASR_DEMO_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--asr-mode", choices=["offline", "online"], default="offline")
    parser.add_argument("--asr-stream", action="store_true", help="Append -s for online streaming mode")
    parser.add_argument("--asr-encoder-device", default="0xff")
    parser.add_argument("--asr-llm-device", default="0xff")
    parser.add_argument("--asr-timeout", type=int, default=300)

    parser.add_argument("--max-asr-sec", type=float, default=30.0, help="Split long merged ASR units to this maximum chunk length")
    parser.add_argument("--min-asr-sec", type=float, default=1.0, help="Skip chunks shorter than this, except when they are the only piece")
    parser.add_argument("--min-target-asr-sec", type=float, default=8.0, help="Avoid standalone trailing ASR chunks shorter than this when splitting")
    parser.add_argument("--merge-same-speaker", dest="merge_same_speaker", action="store_true", default=True, help="Merge adjacent same-speaker diarization segments before ASR")
    parser.add_argument("--no-merge-same-speaker", dest="merge_same_speaker", action="store_false", help="Disable ASR-friendly same-speaker merge")
    parser.add_argument("--merge-gap-sec", type=float, default=3.0, help="Max gap for merging adjacent same-speaker segments")
    parser.add_argument("--bridge-fragment-sec", type=float, default=2.0, help="Allow short unknown_fragment islands up to this length between same-speaker segments")
    parser.add_argument("--pad-sec", type=float, default=0.3, help="Audio padding added to both sides while preserving original timestamps")
    parser.add_argument("--skip-boundary", action="store_true", help="Do not send unknown_boundary chunks to ASR")
    parser.add_argument("--min-boundary-sec", type=float, default=1.0)
    parser.add_argument("--include-fragments", action="store_true", help="Also send unknown_fragment chunks to ASR")
    parser.add_argument("--min-fragment-sec", type=float, default=2.0)
    parser.add_argument("--include-unknown", action="store_true", help="Include other unknown labels")
    parser.add_argument("--turn-merge-gap", type=float, default=1.0)

    parser.add_argument("--limit", type=int, default=0, help="Only run first N ASR chunks; 0 means all")
    parser.add_argument("--plan-only", action="store_true", help="Only write chunk plan; do not cut WAV or run ASR")
    parser.add_argument("--cut-only", action="store_true", help="Cut WAV chunks but do not run ASR")
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--force", action="store_true", help="Overwrite chunk WAVs and transcripts")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    audio_file = Path(args.audio_file)
    diar_file = Path(args.diarization_file)
    out_dir = Path(args.out_dir)
    chunks_dir = out_dir / "chunks_wav"
    raw_dir = out_dir / "asr_raw_logs"
    text_dir = out_dir / "chunk_transcripts"

    require_file(audio_file, "audio file")
    wav_info = get_wav_info(audio_file)
    if wav_info["channels"] != 1:
        raise V1Error(f"expected mono WAV, got channels={wav_info['channels']}: {audio_file}")

    segments = load_diarization(diar_file)
    jobs, asr_units = make_asr_plan(segments, args, float(wav_info["duration"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    plan = {
        "audio_file": str(audio_file),
        "diarization_file": str(diar_file),
        "wav_info": wav_info,
        "args": vars(args),
        "source_segment_count": len(segments),
        "asr_unit_count": len(asr_units),
        "asr_chunk_count": len(jobs),
        "asr_units": asr_units,
        "chunks": jobs,
    }
    write_json(out_dir / "asr_chunk_plan.json", plan)

    print("audio:", audio_file)
    print("diarization:", diar_file)
    print("out_dir:", out_dir)
    print("source_segments:", len(segments))
    print("asr_units:", len(asr_units))
    print("asr_chunks:", len(jobs))
    print("plan:", out_dir / "asr_chunk_plan.json")

    if args.plan_only:
        return 0

    results: List[Dict[str, Any]] = []
    started_all = time.time()
    ok = failed = cached = 0

    for job in jobs:
        idx = int(job["id"])
        wav_path = chunks_dir / job["wav_name"]
        raw_log = raw_dir / f"chunk_{idx:04d}.log"
        txt_path = text_dir / f"chunk_{idx:04d}.txt"
        meta_path = text_dir / f"chunk_{idx:04d}.json"

        print(
            f"\n[{idx}/{len(jobs)}] {fmt_ts(job['start'])}-{fmt_ts(job['end'])} "
            f"{job['speaker']} dur={job['duration']:.2f}s",
            flush=True,
        )

        if args.force or not wav_path.exists():
            cut_info = cut_wav(audio_file, wav_path, float(job["cut_start"]), float(job["cut_end"]))
        else:
            cut_info = {"cached_wav": True}

        result = dict(job)
        result["wav_path"] = str(wav_path)
        result["cut_info"] = cut_info

        if args.cut_only:
            result.update({"status": "cut_only", "text": "", "raw_log": None})
            results.append(result)
            continue

        if args.resume and not args.force and txt_path.exists():
            text = read_text(txt_path).strip()
            result.update({"status": "cached", "text": text, "raw_log": str(raw_log), "elapsed_sec": 0.0})
            cached += 1
            print("cached transcript:", txt_path)
            results.append(result)
            continue

        try:
            asr = run_qwen3_asr(args, wav_path, raw_log)
            result.update({
                "status": asr["status"],
                "returncode": asr["returncode"],
                "elapsed_sec": asr["elapsed_sec"],
                "text": asr["transcript"],
                "raw_log": asr["raw_log"],
            })
            write_text(txt_path, asr["transcript"] + ("\n" if asr["transcript"] else ""))
            write_json(meta_path, result)
            if asr["status"] == "ok":
                ok += 1
                print("text:", asr["transcript"][:120])
            else:
                failed += 1
                print("WARN:", asr["status"], "raw_log:", raw_log)
                if args.stop_on_error:
                    results.append(result)
                    break
        except Exception as exc:  # keep long batch running unless requested otherwise
            failed += 1
            result.update({"status": "exception", "error": str(exc), "text": "", "raw_log": str(raw_log)})
            write_json(meta_path, result)
            print("ERROR:", exc)
            if args.stop_on_error:
                results.append(result)
                break
        results.append(result)

        # Incremental outputs make interrupted long runs useful.
        write_json(out_dir / "asr_chunks_partial.json", results)
        partial_turns = build_turns(results, args.turn_merge_gap)
        write_text(out_dir / "meeting_transcript_partial.txt", "\n".join(transcript_lines(partial_turns)) + "\n")

    total_elapsed = time.time() - started_all
    turns = build_turns(results, args.turn_merge_gap)
    meeting_transcript = "\n".join(transcript_lines(turns))
    chunk_transcript = "\n".join(transcript_lines(results))

    stats = {
        "source_segment_count": len(segments),
        "asr_unit_count": len(asr_units),
        "asr_chunk_count": len(jobs),
        "result_count": len(results),
        "ok": ok,
        "failed": failed,
        "cached": cached,
        "cut_only": bool(args.cut_only),
        "total_elapsed_sec": total_elapsed,
    }
    final = {
        "audio_file": str(audio_file),
        "diarization_file": str(diar_file),
        "out_dir": str(out_dir),
        "wav_info": wav_info,
        "args": vars(args),
        "stats": stats,
        "asr_units": asr_units,
        "chunks": results,
        "turns": turns,
        "meeting_transcript": meeting_transcript,
    }

    write_json(out_dir / "asr_spk_v1_result.json", final)
    write_json(out_dir / "asr_chunks.json", results)
    write_json(out_dir / "asr_turns.json", turns)
    write_text(out_dir / "chunk_transcript.txt", chunk_transcript + ("\n" if chunk_transcript else ""))
    write_text(out_dir / "meeting_transcript.txt", meeting_transcript + ("\n" if meeting_transcript else ""))

    print("\nDONE")
    print("stats:", json.dumps(stats, ensure_ascii=False))
    print("result_json:", out_dir / "asr_spk_v1_result.json")
    print("meeting_transcript:", out_dir / "meeting_transcript.txt")
    print("chunk_transcript:", out_dir / "chunk_transcript.txt")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
    except V1Error as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
