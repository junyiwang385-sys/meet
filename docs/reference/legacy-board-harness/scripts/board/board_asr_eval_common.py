#!/usr/bin/env python3
"""Shared helpers for board-side Qwen3-ASR long-audio evaluation."""

import json
import os
import pathlib
import re
import subprocess
import threading
import time


DEFAULT_ASR_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo"
DEFAULT_ASR_MODEL_DIR = "/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn"
DEFAULT_AUDIO = "/userdata/meeting_agent/data/audio/L_R004S06C01.flac"
DEFAULT_TEXTGRID = "/userdata/meeting_agent/data/audio/L_R004S06C01.TextGrid"


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def preview_text(text, limit=180):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def write_json(path, obj):
    pathlib.Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_out_dir(out_dir, overwrite):
    out_dir = pathlib.Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"out-dir already exists and is not empty: {out_dir}; use --overwrite")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def run_capture(cmd, timeout=None):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + f"\nTIMEOUT: {exc}"


def soxi_info(audio):
    audio = str(audio)
    rc, full = run_capture(["soxi", audio])
    info = {
        "audio": audio,
        "soxi_return_code": rc,
        "soxi_text": full,
        "channels": None,
        "sample_rate": None,
        "duration_seconds": None,
    }
    rc_d, out_d = run_capture(["soxi", "-D", audio])
    if rc_d == 0:
        try:
            info["duration_seconds"] = round(float(out_d.strip()), 3)
        except ValueError:
            pass
    rc_c, out_c = run_capture(["soxi", "-c", audio])
    if rc_c == 0:
        try:
            info["channels"] = int(out_c.strip())
        except ValueError:
            pass
    rc_r, out_r = run_capture(["soxi", "-r", audio])
    if rc_r == 0:
        try:
            info["sample_rate"] = int(float(out_r.strip()))
        except ValueError:
            pass
    return info


def read_meminfo():
    result = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        result[parts[0].rstrip(":")] = int(parts[1])
                    except ValueError:
                        pass
    except OSError:
        pass
    return result


def read_proc_status(pid):
    result = {}
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith(("VmRSS:", "VmHWM:", "VmSize:")):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            result[parts[0].rstrip(":")] = int(parts[1])
                        except ValueError:
                            pass
    except OSError:
        pass
    return result


def child_pids(pid):
    try:
        text = pathlib.Path(f"/proc/{pid}/task/{pid}/children").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return []
    pids = []
    for item in text.split():
        try:
            pids.append(int(item))
        except ValueError:
            pass
    return pids


def process_tree(pid):
    seen = set()
    stack = [pid]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(child_pids(current))
    return sorted(seen)


def kb_to_mb(value):
    if value is None:
        return None
    return round(value / 1024.0, 3)


class MemorySampler:
    def __init__(self, out_path, interval_s=0.5):
        self.out_path = pathlib.Path(out_path)
        self.interval_s = interval_s
        self.targets = {}
        self.samples = []
        self.phase = "startup"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def set_phase(self, phase):
        with self._lock:
            self.phase = phase

    def add_target(self, name, pid):
        with self._lock:
            self.targets[name] = int(pid)

    def start(self):
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval_s * 4))

    def _run(self):
        with open(self.out_path, "a", encoding="utf-8") as fh:
            while not self._stop.is_set():
                sample = self.sample()
                self.samples.append(sample)
                fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
                fh.flush()
                self._stop.wait(self.interval_s)

    def sample(self):
        mem = read_meminfo()
        mem_total = mem.get("MemTotal")
        mem_available = mem.get("MemAvailable")
        board_used = mem_total - mem_available if mem_total is not None and mem_available is not None else None
        with self._lock:
            targets = dict(self.targets)
            phase = self.phase
        proc_info = {}
        for name, pid in targets.items():
            pids = process_tree(pid)
            rss = 0
            vmsize = 0
            hwm = 0
            alive = []
            for item in pids:
                status = read_proc_status(item)
                if not status:
                    continue
                alive.append(item)
                rss += status.get("VmRSS", 0)
                vmsize += status.get("VmSize", 0)
                hwm = max(hwm, status.get("VmHWM", 0))
            proc_info[name] = {"root_pid": pid, "pids": alive, "rss_kb": rss, "hwm_kb": hwm, "vmsize_kb": vmsize}
        return {
            "t": round(time.time(), 3),
            "phase": phase,
            "mem_total_kb": mem_total,
            "mem_available_kb": mem_available,
            "board_used_kb": board_used,
            "processes": proc_info,
        }

    def summary(self):
        if not self.samples:
            return {"samples": 0}
        board_values = [s.get("board_used_kb") for s in self.samples if s.get("board_used_kb") is not None]
        avail_values = [s.get("mem_available_kb") for s in self.samples if s.get("mem_available_kb") is not None]
        baseline = board_values[0] if board_values else None
        peak = max(board_values) if board_values else None
        phase_peaks = {}
        proc_peaks = {}
        for sample in self.samples:
            phase = sample.get("phase", "unknown")
            used = sample.get("board_used_kb")
            if used is not None:
                phase_peaks[phase] = max(phase_peaks.get(phase, 0), used)
            for name, item in sample.get("processes", {}).items():
                current = proc_peaks.setdefault(name, {"rss_kb": 0, "hwm_kb": 0, "vmsize_kb": 0})
                current["rss_kb"] = max(current["rss_kb"], item.get("rss_kb", 0))
                current["hwm_kb"] = max(current["hwm_kb"], item.get("hwm_kb", 0))
                current["vmsize_kb"] = max(current["vmsize_kb"], item.get("vmsize_kb", 0))
        return {
            "samples": len(self.samples),
            "baseline_board_used_mb": kb_to_mb(baseline),
            "board_used_peak_mb": kb_to_mb(peak),
            "board_used_peak_delta_mb": kb_to_mb(peak - baseline) if peak is not None and baseline is not None else None,
            "mem_available_min_mb": kb_to_mb(min(avail_values)) if avail_values else None,
            "phase_board_used_peak_mb": {k: kb_to_mb(v) for k, v in phase_peaks.items()},
            "process_peaks": {
                name: {"rss_peak_mb": kb_to_mb(item["rss_kb"]), "hwm_peak_mb": kb_to_mb(item["hwm_kb"]), "vmsize_peak_mb": kb_to_mb(item["vmsize_kb"])}
                for name, item in proc_peaks.items()
            },
        }


def asr_model_file(model_dir, name):
    path = pathlib.Path(model_dir) / name
    if not path.exists():
        raise FileNotFoundError(f"missing ASR model file: {path}")
    return str(path)


def build_asr_cmd(asr_dir, asr_model_dir, audio, asr_mode="offline", encoder_core="0xff", llm_core="0xff"):
    asr_dir = pathlib.Path(asr_dir)
    model_dir = pathlib.Path(asr_model_dir)
    if asr_mode == "offline":
        exe = asr_dir / "rknn_qwen3_asr_demo"
        encoder = "encoder.rknn"
        encoder_weight = "encoder.weight"
    else:
        exe = asr_dir / "rknn_qwen3_asr_demo_online"
        encoder = "encoder_online.rknn"
        encoder_weight = "encoder_online.weight"
    if not exe.exists():
        raise FileNotFoundError(f"ASR executable not found: {exe}")
    cmd = [
        str(exe),
        asr_model_file(model_dir, encoder),
        asr_model_file(model_dir, encoder_weight),
        asr_model_file(model_dir, "llm.rknn"),
        asr_model_file(model_dir, "llm.weight"),
        asr_model_file(model_dir, "llm.tokenizer.gguf"),
        asr_model_file(model_dir, "llm.embed.bin"),
        encoder_core,
        llm_core,
        str(audio),
    ]
    if asr_mode == "online-stream":
        cmd.append("-s")
    return cmd


def normalize_transcript(text):
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text or "")
    text = text.replace("\r", "\n")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def extract_asr_transcript(raw_log, mode="offline", regex=None):
    text = pathlib.Path(raw_log).read_text(encoding="utf-8", errors="replace")
    if regex:
        match = re.search(regex, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return normalize_transcript(match.group(1) if match.groups() else match.group(0)), "regex"
    text_res_match = re.search(
        r"text\s+res\s*:\s*(.*?)(?:\n\s*-+\s*Finished\s*-+|\n\s*LLM part performance\s*:|\n\s*Audio latency\s*=|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if text_res_match:
        transcript = normalize_transcript(text_res_match.group(1))
        if transcript:
            return transcript, "marker:text res"
    if mode == "online-stream":
        for pattern in [r"Final\s+Commit\s+Result\s*[:：]\s*(.+)", r"final\s+result\s*[:：]\s*(.+)"]:
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            if matches:
                transcript = normalize_transcript(matches[-1])
                if transcript:
                    return transcript, "marker:final"
    noise_words = (
        "rknn", "init", "model", "encoder", "tokenizer", "inference", "total inference",
        "timing", "time cost", "audio duration", "rtf", "performance", "finished", "language res",
    )
    candidates = []
    for line in text.splitlines():
        line = normalize_transcript(line)
        if len(line) < 8:
            continue
        lower = line.lower()
        if any(word in lower for word in noise_words):
            continue
        if re.search(r"[A-Za-z一-鿿]", line):
            candidates.append(line)
    if candidates:
        return normalize_transcript("\n".join(candidates[-5:])), "fallback:lines"
    return "", "none"


def run_asr_once(asr_dir, asr_model_dir, audio, log_path, sampler=None, target_name="asr", asr_mode="offline", regex=None):
    cmd = build_asr_cmd(asr_dir, asr_model_dir, audio, asr_mode=asr_mode)
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    lib_dir = str(pathlib.Path(asr_dir) / "lib")
    old_ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = lib_dir + ((":" + old_ld) if old_ld else "")
    started = time.time()
    with open(log_path, "wb") as log_file:
        proc = subprocess.Popen(cmd, cwd=asr_dir, stdout=log_file, stderr=subprocess.STDOUT, env=env)
        if sampler is not None:
            sampler.add_target(target_name, proc.pid)
        rc = proc.wait()
    elapsed = round(time.time() - started, 3)
    transcript, method = extract_asr_transcript(log_path, mode=asr_mode, regex=regex)
    transcript = normalize_transcript(transcript)
    return {"cmd": cmd, "log": str(log_path), "return_code": rc, "elapsed_seconds": elapsed, "transcript": transcript, "transcript_chars": len(transcript), "extract_method": method}


def decode_textgrid_text(s):
    return s.replace('""', '"').replace("<sil>", " ").strip()


def extract_textgrid_reference(path, tier_name=None):
    if not path:
        return "", {"path": None, "tier": tier_name, "interval_count": 0}
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    if tier_name:
        blocks = re.findall(r"item \[\d+\]:\s*(.*?)(?=\n\s*item \[\d+\]:|\Z)", text, flags=re.DOTALL)
        selected = []
        for block in blocks:
            name_match = re.search(r'name\s*=\s*"([^"]*)"', block)
            if name_match and name_match.group(1) == tier_name:
                selected.append(block)
        search_text = "\n".join(selected)
    else:
        search_text = text
    values = []
    for match in re.finditer(r'text\s*=\s*"((?:[^"]|"")*)"', search_text):
        value = decode_textgrid_text(match.group(1))
        if value:
            values.append(value)
    return normalize_transcript("\n".join(values)), {"path": str(path), "tier": tier_name, "interval_count": len(values), "available_tiers": re.findall(r'name\s*=\s*"([^"]*)"', text)}


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


def distance_metrics(transcript, reference, max_cells=80_000_000):
    ref_chars = normalize_for_distance(reference)
    hyp_chars = normalize_for_distance(transcript)
    char_cells = len(ref_chars) * len(hyp_chars)
    result = {"reference_chars_normalized": len(ref_chars), "transcript_chars_normalized": len(hyp_chars), "cer": None, "char_distance": None, "char_distance_skipped": char_cells > max_cells, "max_distance_cells": max_cells}
    if ref_chars and char_cells <= max_cells:
        dist = levenshtein(hyp_chars, ref_chars)
        result["char_distance"] = dist
        result["cer"] = round(dist / len(ref_chars), 6)
    ref_tokens = tokenize_for_distance(reference)
    hyp_tokens = tokenize_for_distance(transcript)
    token_cells = len(ref_tokens) * len(hyp_tokens)
    result.update({"reference_tokens": len(ref_tokens), "transcript_tokens": len(hyp_tokens), "token_error_rate": None, "token_distance": None, "token_distance_skipped": token_cells > max_cells})
    if ref_tokens and token_cells <= max_cells:
        dist = levenshtein(hyp_tokens, ref_tokens)
        result["token_distance"] = dist
        result["token_error_rate"] = round(dist / len(ref_tokens), 6)
    return result


def completeness_flags(audio_duration, elapsed, transcript_chars, reference_chars):
    rtf = round(elapsed / audio_duration, 6) if audio_duration else None
    ref_ratio = round(transcript_chars / reference_chars, 6) if reference_chars else None
    suspicious = False
    reasons = []
    if audio_duration and audio_duration >= 600 and transcript_chars < 1500:
        suspicious = True
        reasons.append("long_audio_short_transcript")
    if ref_ratio is not None and ref_ratio < 0.5:
        suspicious = True
        reasons.append("transcript_much_shorter_than_reference")
    if rtf is not None and audio_duration >= 600 and rtf < 0.03:
        suspicious = True
        reasons.append("very_low_rtf_for_long_audio")
    return {"rtf": rtf, "suspicious": suspicious, "suspicious_reasons": reasons, "transcript_reference_char_ratio": ref_ratio}
