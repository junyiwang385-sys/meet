#!/usr/bin/env python3
"""Run board-side Qwen3-ASR -> rkllm3-server meeting summary chain.

The script is intended to run on the RK1828 board and uses only Python's
standard library. It stores full logs/results and samples /proc memory usage
while the ASR and LLM stages are running.
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import threading
import time
import urllib.request


DEFAULT_ASR_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo"
DEFAULT_ASR_MODEL_DIR = "/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn"
DEFAULT_AUDIO = "/userdata/meeting_agent/data/audio/asr_en.wav"
DEFAULT_MODEL_DIR = "/userdata/meeting_agent/models/llm/v104/qwen2.5-7b-v104"
DEFAULT_SERVER = "/usr/bin/rkllm3-server"
DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/e2e/run"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18231

REQUIRED_LLM_SUFFIXES = {
    "model": ".rknn",
    "weight": ".weight",
    "vocab": ".tokenizer.gguf",
    "embed": ".embed.bin",
}

DEFAULT_PROMPT_TEMPLATE = """你是一个中文会议纪要助手。只根据下面的ASR转写内容生成会议总结。

要求：
- 只输出合法JSON对象，不要输出Markdown或解释。
- 不要编造转写中没有的信息；不明确的负责人、时间、结论写“未明确”。
- 忽略口头禅、重复语和明显识别噪声；可纠正明显ASR错字但不要改变原意。
- 内容要具体，但字段要紧凑；每个数组最多6条。
- 如果没有发言人标签，speakers 写一个 speaker_1，说明为“未明确具体发言人”。
- refs 使用简短片段范围；如果输入没有片段编号，写“未明确”。

JSON结构：
{
  "title": "一句话会议主题",
  "summary": "3到5句话总结会议内容",
  "speakers": [
    {
      "id": "speaker_1",
      "refs": "segment 001-020 或 未明确",
      "summary": "该发言人主要内容"
    }
  ],
  "topics": [
    {
      "name": "主题名称",
      "refs": "segment 001-020 或 未明确",
      "speakers": ["speaker_1"],
      "problem": "问题或现状，未明确则写未明确",
      "discussion": "讨论方案或观点",
      "decision": "明确决定，未明确则写未明确",
      "next": "后续工作，未明确则写未明确"
    }
  ],
  "actions": [
    {
      "task": "待办事项",
      "owner": "未明确",
      "deadline": "未明确"
    }
  ],
  "questions": ["仍需确认的问题"],
  "risks": ["风险、限制或依赖项"],
  "key_points": ["重要讨论点"]
}

ASR转写：
{transcript}
"""


def now_ts():
    return round(time.time(), 3)


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def preview_text(text, limit=180):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def kb_to_mb(value):
    if value is None:
        return None
    return round(value / 1024.0, 3)


def read_meminfo():
    result = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    try:
                        result[key] = int(parts[1])
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
                if not line.startswith(("VmRSS:", "VmHWM:", "VmSize:")):
                    continue
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
    path = f"/proc/{pid}/task/{pid}/children"
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace").strip()
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


def sample_process_tree(root_pid):
    pids = process_tree(root_pid)
    total_rss = 0
    total_size = 0
    max_hwm = 0
    alive = []
    for pid in pids:
        status = read_proc_status(pid)
        if not status:
            continue
        alive.append(pid)
        total_rss += status.get("VmRSS", 0)
        total_size += status.get("VmSize", 0)
        max_hwm = max(max_hwm, status.get("VmHWM", 0))
    return {
        "root_pid": root_pid,
        "pids": alive,
        "rss_kb": total_rss,
        "hwm_kb": max_hwm,
        "vmsize_kb": total_size,
    }


class MemorySampler:
    def __init__(self, out_path, interval_s=0.2):
        self.out_path = pathlib.Path(out_path)
        self.interval_s = interval_s
        self.phase = "startup"
        self.targets = {}
        self.samples = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def set_phase(self, phase):
        with self._lock:
            self.phase = phase

    def add_target(self, name, pid):
        if pid is None:
            return
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
                sample = self._sample_once()
                self.samples.append(sample)
                fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
                fh.flush()
                self._stop.wait(self.interval_s)

    def _sample_once(self):
        with self._lock:
            phase = self.phase
            targets = dict(self.targets)
        meminfo = read_meminfo()
        total = meminfo.get("MemTotal")
        available = meminfo.get("MemAvailable")
        used = total - available if total is not None and available is not None else None
        proc = {name: sample_process_tree(pid) for name, pid in targets.items()}
        return {
            "ts": now_ts(),
            "phase": phase,
            "meminfo": meminfo,
            "board_used_kb": used,
            "processes": proc,
        }

    def summary(self):
        if not self.samples:
            return {}
        baseline = self.samples[0].get("board_used_kb")
        board_peak = None
        mem_available_min = None
        phase_peaks = {}
        proc_peaks = {}
        for sample in self.samples:
            used = sample.get("board_used_kb")
            phase = sample.get("phase", "unknown")
            if used is not None:
                board_peak = used if board_peak is None else max(board_peak, used)
                phase_peaks[phase] = max(phase_peaks.get(phase, used), used)
            available = sample.get("meminfo", {}).get("MemAvailable")
            if available is not None:
                mem_available_min = available if mem_available_min is None else min(mem_available_min, available)
            for name, proc in sample.get("processes", {}).items():
                item = proc_peaks.setdefault(name, {"rss_peak_kb": 0, "hwm_peak_kb": 0, "vmsize_peak_kb": 0})
                item["rss_peak_kb"] = max(item["rss_peak_kb"], proc.get("rss_kb", 0))
                item["hwm_peak_kb"] = max(item["hwm_peak_kb"], proc.get("hwm_kb", 0))
                item["vmsize_peak_kb"] = max(item["vmsize_peak_kb"], proc.get("vmsize_kb", 0))
        return {
            "samples": len(self.samples),
            "baseline_board_used_mb": kb_to_mb(baseline),
            "board_used_peak_mb": kb_to_mb(board_peak),
            "board_used_peak_delta_mb": kb_to_mb(board_peak - baseline) if board_peak is not None and baseline is not None else None,
            "mem_available_min_mb": kb_to_mb(mem_available_min),
            "phase_board_used_peak_mb": {k: kb_to_mb(v) for k, v in phase_peaks.items()},
            "process_peaks": {
                name: {
                    "rss_peak_mb": kb_to_mb(item["rss_peak_kb"]),
                    "hwm_peak_mb": kb_to_mb(item["hwm_peak_kb"]),
                    "vmsize_peak_mb": kb_to_mb(item["vmsize_peak_kb"]),
                }
                for name, item in proc_peaks.items()
            },
        }


def write_json(path, obj):
    pathlib.Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def find_file(model_dir, suffix):
    model_dir = pathlib.Path(model_dir)
    matches = sorted(model_dir.glob(f"*{suffix}"))
    if not matches:
        raise FileNotFoundError(f"missing *{suffix} in {model_dir}")
    return str(matches[0])


def discover_llm_files(model_dir):
    return {key: find_file(model_dir, suffix) for key, suffix in REQUIRED_LLM_SUFFIXES.items()}


def asr_model_file(model_dir, name):
    path = pathlib.Path(model_dir) / name
    if not path.exists():
        raise FileNotFoundError(f"missing ASR model file: {path}")
    return str(path)


def build_asr_cmd(args):
    asr_dir = pathlib.Path(args.asr_dir)
    model_dir = pathlib.Path(args.asr_model_dir) if args.asr_model_dir else asr_dir / "model"
    if args.asr_mode == "offline":
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
        args.asr_encoder_core,
        args.asr_llm_core,
        str(pathlib.Path(args.audio)),
    ]
    if args.asr_mode == "online-stream":
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


def extract_asr_transcript(raw_log, mode, regex=None):
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
        patterns = [
            r"Final\s+Commit\s+Result\s*[:：]\s*(.+)",
            r"final\s+result\s*[:：]\s*(.+)",
        ]
        for pattern in patterns:
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


def load_prompt_template(path):
    if path:
        p = pathlib.Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
        raise FileNotFoundError(f"prompt template not found: {p}")
    return DEFAULT_PROMPT_TEMPLATE


def build_messages(transcript, prompt_template):
    prompt = prompt_template.replace("{transcript}", transcript)
    return [{"role": "user", "content": prompt}]


def build_llm_cmd(args, files):
    return [
        args.server,
        "-m", files["model"],
        "--weight", files["weight"],
        "--vocab", files["vocab"],
        "--embed", files["embed"],
        "-c", str(args.ctx),
        "-n", str(args.predict),
        "--temp", str(args.server_temp),
        "--top-k", str(args.server_top_k),
        "--top-p", str(args.server_top_p),
        "--repeat-penalty", str(args.server_repeat_penalty),
        "--host", args.host,
        "--port", str(args.port),
    ]


def wait_ready(host, port, timeout_s):
    start = time.time()
    url = f"http://{host}:{port}/health"
    while time.time() - start < timeout_s:
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return round(time.time() - start, 3)
        except Exception:
            time.sleep(1)
    return None


def post_chat(host, port, payload, timeout_s):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    raw = urllib.request.urlopen(req, timeout=timeout_s).read().decode("utf-8", "replace")
    return raw, json.loads(raw)


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start:end + 1]


def terminate_process(proc, timeout_s=10):
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def prepare_out_dir(out_dir, overwrite):
    out_dir = pathlib.Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"out-dir already exists and is not empty: {out_dir}; use --overwrite")
        log(f"[WARN] out-dir exists; files may be overwritten but stale extra files can remain: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def run_asr(args, out_dir, sampler):
    cmd = build_asr_cmd(args)
    write_json(out_dir / "asr_cmd.json", cmd)
    log_path = out_dir / "asr_raw.log"
    sampler.set_phase("asr")
    env = dict(os.environ)
    lib_dir = str(pathlib.Path(args.asr_dir) / "lib")
    old_ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = lib_dir + ((":" + old_ld) if old_ld else "")
    log(f"[ASR] start mode={args.asr_mode}")
    log(f"[ASR] runtime={args.asr_dir}")
    log(f"[ASR] model={args.asr_model_dir}")
    log(f"[ASR] audio={args.audio}")
    started = time.time()
    with open(log_path, "wb") as log_file:
        proc = subprocess.Popen(cmd, cwd=args.asr_dir, stdout=log_file, stderr=subprocess.STDOUT, env=env)
        sampler.add_target("asr", proc.pid)
        log(f"[ASR] pid={proc.pid}, log={log_path}")
        rc = proc.wait()
    elapsed = round(time.time() - started, 3)
    log(f"[ASR] done return_code={rc}, elapsed={elapsed}s")
    transcript, method = extract_asr_transcript(log_path, args.asr_mode, args.asr_transcript_regex)
    transcript = normalize_transcript(transcript)
    (out_dir / "transcript_raw.txt").write_text(transcript, encoding="utf-8")
    (out_dir / "transcript_normalized.txt").write_text(transcript, encoding="utf-8")
    log(f"[ASR] transcript_chars={len(transcript)}, extract_method={method}")
    if transcript:
        log(f"[ASR] transcript_preview={preview_text(transcript)}")
    return {
        "cmd": cmd,
        "log": str(log_path),
        "return_code": rc,
        "elapsed_seconds": elapsed,
        "transcript": transcript,
        "transcript_chars": len(transcript),
        "extract_method": method,
    }


def run_llm(args, out_dir, sampler, transcript):
    files = discover_llm_files(args.model_dir)
    cmd = build_llm_cmd(args, files)
    write_json(out_dir / "llm_cmd.json", cmd)
    prompt_template = load_prompt_template(args.prompt_template)
    messages = build_messages(transcript, prompt_template)
    write_json(out_dir / "messages.json", messages)
    payload = {
        "model": "default",
        "messages": messages,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
    }
    if args.response_format_json_object:
        payload["response_format"] = {"type": "json_object"}
    write_json(out_dir / "llm_request.json", payload)

    log_path = out_dir / "rkllm_server.log"
    sampler.set_phase("llm_server_start")
    proc = None
    result = {"status": "unknown", "cmd": cmd, "files": files, "server_log": str(log_path)}
    try:
        log(f"[LLM] start rkllm3-server model_dir={args.model_dir}")
        log(f"[LLM] ctx={args.ctx}, predict={args.predict}, max_tokens={args.max_tokens}, port={args.port}")
        with open(log_path, "wb") as log_file:
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
            sampler.add_target("rkllm_server", proc.pid)
            log(f"[LLM] server pid={proc.pid}, log={log_path}")
            log(f"[LLM] waiting for health http://{args.host}:{args.port}/health")
            ready = wait_ready(args.host, args.port, args.ready_timeout)
            result["ready_seconds"] = ready
            if ready is None:
                result["status"] = "server_not_ready"
                log("[LLM] server_not_ready")
                return result
            log(f"[LLM] server ready in {ready}s")
            sampler.set_phase("llm_request")
            log("[LLM] request start")
            started = time.time()
            raw, resp = post_chat(args.host, args.port, payload, args.request_timeout)
            elapsed = round(time.time() - started, 3)
        log(f"[LLM] request done elapsed={elapsed}s")
        (out_dir / "llm_response.json").write_text(raw, encoding="utf-8")
        choice = resp.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        result.update(
            {
                "status": "ok",
                "elapsed_seconds": elapsed,
                "finish_reason": choice.get("finish_reason"),
                "usage": resp.get("usage"),
                "timings": resp.get("timings"),
                "content": content,
            }
        )
        log(f"[LLM] finish_reason={choice.get('finish_reason')}, usage={resp.get('usage')}")
        log(f"[LLM] content_preview={preview_text(content)}")
        payload_text = extract_json(content)
        if payload_text is None:
            result["json_valid"] = False
            result["json_error"] = "no_json_object_found"
            log("[LLM] json_valid=False, error=no_json_object_found")
        else:
            try:
                parsed = json.loads(payload_text)
                result["json_valid"] = True
                result["parsed"] = parsed
                write_json(out_dir / "summary.json", parsed)
                log(f"[LLM] json_valid=True, summary={out_dir / 'summary.json'}")
            except Exception as exc:
                result["json_valid"] = False
                result["json_error"] = repr(exc)
                log(f"[LLM] json_valid=False, error={repr(exc)}")
        write_json(out_dir / "result.json", result)
        return result
    except Exception as exc:
        result["status"] = "error"
        result["error"] = repr(exc)
        log(f"[LLM] error={repr(exc)}")
        write_json(out_dir / "result.json", result)
        return result
    finally:
        sampler.set_phase("cleanup")
        if proc is not None:
            terminate_process(proc)
            log("[LLM] server stopped")


def parse_args():
    parser = argparse.ArgumentParser(description="Run board Qwen3-ASR -> rkllm3-server meeting-summary chain and profile memory.")
    parser.add_argument("--audio", default=DEFAULT_AUDIO, help="Input audio file path")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output run directory")
    parser.add_argument("--overwrite", action="store_true", help="Allow writing into an existing non-empty output directory")

    parser.add_argument("--asr-dir", default=DEFAULT_ASR_DIR, help="Qwen3-ASR demo runtime directory containing executables and lib/")
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR, help="Qwen3-ASR RKNN model directory; defaults to unified board path")
    parser.add_argument("--asr-mode", choices=["offline", "online", "online-stream"], default="offline")
    parser.add_argument("--asr-transcript-regex", help="Optional regex used to extract transcript from ASR log")
    parser.add_argument("--asr-encoder-core", default="0xff")
    parser.add_argument("--asr-llm-core", default="0xff")

    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR, help="LLM model directory containing .rknn/.weight/.tokenizer.gguf/.embed.bin")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ctx", type=int, default=4096)
    parser.add_argument("--predict", type=int, default=1024)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0, help="HTTP generation temperature")
    parser.add_argument("--server-temp", type=float, default=0.0)
    parser.add_argument("--server-top-k", type=int, default=1)
    parser.add_argument("--server-top-p", type=float, default=1.0)
    parser.add_argument("--server-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--no-response-format", dest="response_format_json_object", action="store_false")
    parser.set_defaults(response_format_json_object=True)

    parser.add_argument("--prompt-template", help="Prompt template file containing {transcript}; defaults to built-in compact Chinese JSON prompt")
    parser.add_argument("--sample-interval", type=float, default=0.2, help="Memory sampling interval in seconds")
    return parser.parse_args()


def main():
    args = parse_args()
    log("[CHAIN] start board meeting chain")
    out_dir = prepare_out_dir(args.out_dir, args.overwrite)
    log(f"[CHAIN] out_dir={out_dir}")
    write_json(out_dir / "run_config.json", vars(args))

    sampler = MemorySampler(out_dir / "memory_samples.jsonl", interval_s=args.sample_interval)
    sampler.start()
    log(f"[MEM] sampling interval={args.sample_interval}s, samples={out_dir / 'memory_samples.jsonl'}")
    chain = {
        "status": "unknown",
        "audio": args.audio,
        "asr_mode": args.asr_mode,
        "asr_dir": args.asr_dir,
        "asr_model_dir": args.asr_model_dir,
        "model_dir": args.model_dir,
        "out_dir": str(out_dir),
    }
    exit_code = 1
    try:
        asr_result = run_asr(args, out_dir, sampler)
        chain.update(
            {
                "asr_elapsed_seconds": asr_result["elapsed_seconds"],
                "asr_return_code": asr_result["return_code"],
                "asr_extract_method": asr_result["extract_method"],
                "transcript_chars": asr_result["transcript_chars"],
            }
        )
        if asr_result["return_code"] != 0 or not asr_result["transcript"]:
            chain["status"] = "asr_failed_or_empty"
            log("[CHAIN] stop: ASR failed or transcript is empty")
            exit_code = 2
            return exit_code

        llm_result = run_llm(args, out_dir, sampler, asr_result["transcript"])
        chain.update(
            {
                "llm_status": llm_result.get("status"),
                "llm_ready_seconds": llm_result.get("ready_seconds"),
                "llm_elapsed_seconds": llm_result.get("elapsed_seconds"),
                "finish_reason": llm_result.get("finish_reason"),
                "json_valid": llm_result.get("json_valid"),
                "usage": llm_result.get("usage"),
                "timings": llm_result.get("timings"),
            }
        )
        if llm_result.get("status") == "server_not_ready":
            chain["status"] = "llm_server_not_ready"
            exit_code = 3
        elif llm_result.get("status") != "ok":
            chain["status"] = "llm_error"
            chain["error"] = llm_result.get("error")
            exit_code = 4
        elif not llm_result.get("json_valid"):
            chain["status"] = "llm_json_invalid"
            chain["json_error"] = llm_result.get("json_error")
            exit_code = 5
        else:
            chain["status"] = "ok"
            exit_code = 0
        log(f"[CHAIN] status={chain['status']}, exit_code={exit_code}")
        return exit_code
    except Exception as exc:
        chain["status"] = "error"
        chain["error"] = repr(exc)
        log(f"[CHAIN] error={repr(exc)}")
        exit_code = 1
        return exit_code
    finally:
        sampler.stop()
        memory_summary = sampler.summary()
        write_json(out_dir / "memory_summary.json", memory_summary)
        log(f"[MEM] board_used_peak_mb={memory_summary.get('board_used_peak_mb')}, delta_mb={memory_summary.get('board_used_peak_delta_mb')}, mem_available_min_mb={memory_summary.get('mem_available_min_mb')}")
        chain["memory"] = memory_summary
        chain["outputs"] = {
            "run_config": str(out_dir / "run_config.json"),
            "asr_raw_log": str(out_dir / "asr_raw.log"),
            "transcript_normalized": str(out_dir / "transcript_normalized.txt"),
            "rkllm_server_log": str(out_dir / "rkllm_server.log"),
            "llm_response": str(out_dir / "llm_response.json"),
            "summary": str(out_dir / "summary.json"),
            "memory_summary": str(out_dir / "memory_summary.json"),
            "memory_samples": str(out_dir / "memory_samples.jsonl"),
        }
        write_json(out_dir / "chain_summary.json", chain)
        log(f"[OUTPUT] chain_summary={out_dir / 'chain_summary.json'}")
        log(f"[OUTPUT] memory_summary={out_dir / 'memory_summary.json'}")
        log(f"[OUTPUT] summary={out_dir / 'summary.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
