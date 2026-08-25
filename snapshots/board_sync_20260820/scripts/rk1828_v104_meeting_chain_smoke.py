#!/usr/bin/env python3
"""RK1828 v1.0.4 short meeting-chain smoke test.

Runs one of:
  audio wav -> Qwen3-ASR demo -> transcript -> rkllm3-server/Qwen -> strict JSON
  transcript txt -> rkllm3-server/Qwen -> strict JSON

This script intentionally uses only Python standard library so it can be copied
straight to the RK1828 board.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


DEFAULT_ASR_DEMO_DIR = "/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo"
DEFAULT_ASR_MODEL_DIR = "/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn"
DEFAULT_MODEL_DIR = "/userdata/meeting_agent/models/llm/v100/qwen3-4b-lifelog-real-ctx8k"
DEFAULT_SERVER = "/usr/bin/rkllm3-server"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18203
DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/e2e/meeting_chain_smoke"

SYSTEM_PROMPT = (
    "你是会议纪要助手。必须只输出一个合法 JSON 对象；不要输出 Markdown、代码块、解释或 JSON 以外的文字。"
    "只能根据 ASR 转写内容总结，不要编造转写中没有的信息。"
)

EMBEDDED_PROMPT_TEMPLATE = """你是中文会议纪要助手。只根据 ASR 转写生成紧凑 JSON。

要求：
- 只输出 JSON 对象本身，不要 Markdown，不要解释，不要工具调用标签。
- 不要编造转写中没有的信息；不明确的负责人、时间、结论写“未明确”。
- 没有发言人标签时，speakers 使用一个 speaker_1。
- 每个数组最多 6 条。

必须输出这些字段和类型：
{
  "title": "字符串",
  "summary": "字符串",
  "speakers": [{"id": "speaker_1", "refs": "未明确", "summary": "字符串"}],
  "topics": [{"name": "字符串", "refs": "未明确", "speakers": ["speaker_1"], "problem": "字符串", "discussion": "字符串", "decision": "未明确", "next": "未明确"}],
  "actions": [{"task": "字符串", "owner": "未明确", "deadline": "未明确"}],
  "questions": ["字符串"],
  "risks": ["字符串"],
  "key_points": ["字符串"]
}

ASR转写：
{transcript}
"""

REQUIRED_SUFFIXES = {
    "rknn": ".rknn",
    "weight": ".weight",
    "vocab": ".tokenizer.gguf",
    "embed": ".embed.bin",
}

EXIT_RUNTIME = 1
EXIT_ENV = 2
EXIT_JSON = 3
EXIT_ASR = 4


class ChainError(Exception):
    exit_code = EXIT_RUNTIME


class EnvError(ChainError):
    exit_code = EXIT_ENV


class JsonValidationError(ChainError):
    exit_code = EXIT_JSON


class AsrError(ChainError):
    exit_code = EXIT_ASR


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise EnvError(f"{label} not found: {path}")


def require_executable(path: Path, label: str) -> None:
    if not path.is_file():
        raise EnvError(f"{label} not found: {path}")
    if not os.access(str(path), os.X_OK):
        raise EnvError(f"{label} is not executable: {path}")


def find_one_by_suffix(model_dir: Path, suffix: str, label: str) -> Path:
    matches = sorted(p for p in model_dir.iterdir() if p.is_file() and p.name.endswith(suffix))
    if not matches:
        raise EnvError(f"missing {label} (*{suffix}) in {model_dir}")
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise EnvError(
            f"multiple {label} files in {model_dir}: {names}; use explicit --llm-{label}"
        )
    return matches[0]


def discover_llm_files(args: argparse.Namespace) -> Dict[str, Path]:
    model_dir = Path(args.model_dir)
    if not model_dir.is_dir():
        raise EnvError(f"model dir not found: {model_dir}")

    explicit = {
        "rknn": args.llm_rknn,
        "weight": args.llm_weight,
        "vocab": args.llm_vocab,
        "embed": args.llm_embed,
    }
    result: Dict[str, Path] = {}
    for key, suffix in REQUIRED_SUFFIXES.items():
        if explicit[key]:
            p = Path(explicit[key])
            require_file(p, f"LLM {key}")
            result[key] = p
        else:
            result[key] = find_one_by_suffix(model_dir, suffix, key)
    return result


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
    # Prefer actual language content. Accept Chinese, or a reasonably long text line.
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

    # Do not fall back to arbitrary language-like log lines. Qwen3-ASR prints many
    # English tokenizer/runtime lines; accepting those can create a false transcript
    # when RKNN init fails. Treat missing known result markers as ASR parse failure.
    return ""


def run_qwen3_asr(args: argparse.Namespace, out_dir: Path) -> str:
    demo_dir = Path(args.asr_demo_dir)
    if not demo_dir.is_dir():
        raise EnvError(f"ASR demo dir not found: {demo_dir}")
    asr_model_dir = Path(args.asr_model_dir)
    if not asr_model_dir.is_dir():
        raise EnvError(f"ASR model dir not found: {asr_model_dir}")
    audio_file = Path(args.audio_file)
    require_file(audio_file, "audio file")

    if args.asr_mode == "offline":
        binary = demo_dir / "rknn_qwen3_asr_demo"
        model_files = [
            asr_model_dir / "encoder.rknn",
            asr_model_dir / "encoder.weight",
            asr_model_dir / "llm.rknn",
            asr_model_dir / "llm.weight",
            asr_model_dir / "llm.tokenizer.gguf",
            asr_model_dir / "llm.embed.bin",
        ]
    else:
        binary = demo_dir / "rknn_qwen3_asr_demo_online"
        model_files = [
            asr_model_dir / "encoder_online.rknn",
            asr_model_dir / "encoder_online.weight",
            asr_model_dir / "llm.rknn",
            asr_model_dir / "llm.weight",
            asr_model_dir / "llm.tokenizer.gguf",
            asr_model_dir / "llm.embed.bin",
        ]

    cmd = [str(binary)] + [str(p) for p in model_files] + [
        args.asr_encoder_device,
        args.asr_llm_device,
        str(audio_file),
    ]
    if args.asr_mode == "online" and args.asr_stream:
        cmd.append("-s")

    require_executable(binary, "ASR binary")
    for p in model_files:
        require_file(p, f"ASR model file {p.name}")

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
    write_text(out_dir / "asr_raw.log", raw)
    write_json(out_dir / "asr_command.json", {"cmd": cmd, "cwd": str(demo_dir), "returncode": proc.returncode, "elapsed_sec": elapsed})

    if proc.returncode != 0:
        raise AsrError(f"ASR command failed with code {proc.returncode}; see {out_dir / 'asr_raw.log'}")

    transcript = parse_qwen3_asr_output(raw)
    if not transcript.strip():
        raise AsrError(f"ASR transcript is empty or could not be parsed; see {out_dir / 'asr_raw.log'}")
    return transcript.strip()


def load_transcript(args: argparse.Namespace, out_dir: Path) -> str:
    if args.transcript_file:
        transcript_path = Path(args.transcript_file)
        require_file(transcript_path, "transcript file")
        transcript = read_text(transcript_path).strip()
    else:
        transcript = run_qwen3_asr(args, out_dir).strip()

    if not transcript:
        raise AsrError("transcript is empty")
    write_text(out_dir / "transcript.txt", transcript + "\n")
    return transcript


def load_prompt_template(args: argparse.Namespace) -> Tuple[str, str]:
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        require_file(prompt_path, "prompt file")
        return read_text(prompt_path), str(prompt_path)
    return EMBEDDED_PROMPT_TEMPLATE, "embedded:meeting_minutes_compact_json_zh"


def build_messages(prompt_template: str, transcript: str) -> List[Dict[str, str]]:
    if "{transcript}" in prompt_template:
        user_prompt = prompt_template.replace("{transcript}", transcript)
    else:
        user_prompt = prompt_template.rstrip() + "\n\nASR转写：\n" + transcript
    # Qwen3-4B on this board can emit an immediate EOS with separate system+user
    # messages for the long JSON prompt. A single user message matches the
    # verified working request format more closely.
    return [
        {"role": "user", "content": user_prompt},
    ]


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_ready(host: str, port: int, timeout_s: int) -> None:
    url = f"http://{host}:{port}/health"
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001 - status polling should keep retrying
            last_error = str(exc)
        time.sleep(1)
    raise EnvError(f"rkllm3-server not ready at {url}; last error: {last_error}")


def start_llm_server(args: argparse.Namespace, llm_files: Dict[str, Path], server_log: Path) -> Optional[subprocess.Popen[Any]]:
    if args.reuse_server:
        wait_ready(args.host, args.port, args.ready_timeout)
        return None

    if is_port_open(args.host, args.port):
        raise EnvError(f"port {args.host}:{args.port} is already open; use --reuse-server or choose --port")

    server = Path(args.server)
    require_executable(server, "rkllm3-server")

    cmd = [
        str(server),
        "-m",
        str(llm_files["rknn"]),
        "--weight",
        str(llm_files["weight"]),
        "--vocab",
        str(llm_files["vocab"]),
        "--embed",
        str(llm_files["embed"]),
        "-c",
        str(args.ctx),
        "-n",
        str(args.predict),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.server_temp is not None:
        cmd += ["--temp", str(args.server_temp)]
    if args.server_top_k is not None:
        cmd += ["--top-k", str(args.server_top_k)]
    if args.server_top_p is not None:
        cmd += ["--top-p", str(args.server_top_p)]
    if args.server_repeat_penalty is not None:
        cmd += ["--repeat-penalty", str(args.server_repeat_penalty)]

    log_f = server_log.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path(args.model_dir)),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Keep a reference so the file is not garbage collected before process exits.
    proc._rk1828_log_file = log_f  # type: ignore[attr-defined]

    try:
        wait_ready(args.host, args.port, args.ready_timeout)
    except Exception:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        log_f.close()
        raise
    return proc


def stop_llm_server(proc: Optional[subprocess.Popen[Any]], keep: bool) -> None:
    if proc is None:
        return
    if keep:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    log_f = getattr(proc, "_rk1828_log_file", None)
    if log_f is not None:
        log_f.close()


def post_chat(args: argparse.Namespace, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": "qwen3-4b",
        "messages": messages,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    if args.response_format_json_object:
        payload["response_format"] = {"type": "json_object"}

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://{args.host}:{args.port}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=args.request_timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ChainError(f"LLM HTTP {exc.code}: {body[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise ChainError(f"LLM request failed: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ChainError(f"LLM response is not JSON: {exc}; body={body[:1000]}") from exc


def get_response_content(response: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise JsonValidationError("response missing choices[0]")
    first = choices[0]
    if not isinstance(first, dict):
        raise JsonValidationError("choices[0] is not object")
    finish_reason = first.get("finish_reason")
    message = first.get("message")
    if not isinstance(message, dict):
        raise JsonValidationError("choices[0].message is not object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise JsonValidationError("choices[0].message.content is empty")
    return content, finish_reason if isinstance(finish_reason, str) else None


def find_first_json_object_text(content: str) -> Optional[str]:
    start = content.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(content)):
            ch = content[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return content[start : idx + 1]
                if depth < 0:
                    break
        start = content.find("{", start + 1)
    return None


def add_error(errors: List[str], path: str, expected: str, value: Any) -> None:
    errors.append(f"{path} expected {expected}, got {type(value).__name__}")


def require_type(errors: List[str], obj: Dict[str, Any], key: str, typ: type, path: str) -> None:
    if key not in obj:
        errors.append(f"{path}.{key} missing")
    elif not isinstance(obj[key], typ):
        add_error(errors, f"{path}.{key}", typ.__name__, obj[key])


def validate_compact_schema(data: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(data, dict):
        return [f"$ expected object, got {type(data).__name__}"]

    for key in ["title", "summary"]:
        require_type(errors, data, key, str, "$")
    for key in ["speakers", "topics", "actions", "questions", "risks", "key_points"]:
        require_type(errors, data, key, list, "$")

    for idx, item in enumerate(data.get("speakers", []) if isinstance(data.get("speakers"), list) else []):
        path = f"$.speakers[{idx}]"
        if not isinstance(item, dict):
            add_error(errors, path, "object", item)
            continue
        for key in ["id", "refs", "summary"]:
            require_type(errors, item, key, str, path)

    for idx, item in enumerate(data.get("topics", []) if isinstance(data.get("topics"), list) else []):
        path = f"$.topics[{idx}]"
        if not isinstance(item, dict):
            add_error(errors, path, "object", item)
            continue
        for key in ["name", "refs", "problem", "discussion", "decision", "next"]:
            require_type(errors, item, key, str, path)
        require_type(errors, item, "speakers", list, path)
        speakers = item.get("speakers")
        if isinstance(speakers, list):
            for j, speaker in enumerate(speakers):
                if not isinstance(speaker, str):
                    add_error(errors, f"{path}.speakers[{j}]", "str", speaker)

    for idx, item in enumerate(data.get("actions", []) if isinstance(data.get("actions"), list) else []):
        path = f"$.actions[{idx}]"
        if not isinstance(item, dict):
            add_error(errors, path, "object", item)
            continue
        for key in ["task", "owner", "deadline"]:
            require_type(errors, item, key, str, path)

    for field in ["questions", "risks", "key_points"]:
        values = data.get(field)
        if isinstance(values, list):
            for idx, item in enumerate(values):
                if not isinstance(item, str):
                    add_error(errors, f"$.{field}[{idx}]", "str", item)
    return errors


def parse_and_validate_content(content: str, finish_reason: Optional[str]) -> Tuple[Dict[str, Any], List[str], bool]:
    stripped = content.strip()
    used_extraction = False
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as full_exc:
        json_text = find_first_json_object_text(content)
        if not json_text:
            raise JsonValidationError(f"model content has no JSON object: {full_exc}") from full_exc
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as extract_exc:
            raise JsonValidationError(f"extracted JSON object is invalid: {extract_exc}") from extract_exc
        used_extraction = True
    errors = validate_compact_schema(parsed)
    if finish_reason and finish_reason.lower() in {"length", "max_tokens"}:
        errors.append(f"finish_reason indicates truncation: {finish_reason}")
    if errors:
        raise JsonValidationError("schema validation failed: " + "; ".join(errors))
    return parsed, errors, used_extraction


def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RK1828 v1.0.4 Chinese audio/transcript -> Qwen3-ASR -> Qwen3-4B strict JSON chain smoke test")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--audio-file", help="Board-local wav file for Qwen3-ASR")
    inputs.add_argument("--transcript-file", help="Board-local transcript text file to skip ASR")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)

    parser.add_argument("--asr-demo-dir", default=DEFAULT_ASR_DEMO_DIR)
    parser.add_argument("--asr-model-dir", default=DEFAULT_ASR_MODEL_DIR)
    parser.add_argument("--asr-mode", choices=["offline", "online"], default="offline")
    parser.add_argument("--asr-stream", action="store_true", help="Append -s for online streaming mode")
    parser.add_argument("--asr-encoder-device", default="0xff")
    parser.add_argument("--asr-llm-device", default="0xff")
    parser.add_argument("--asr-timeout", type=int, default=900)

    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR, help="Default is Qwen3-4B board model dir")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--ctx", type=int, default=4096)
    parser.add_argument("--predict", type=int, default=1024)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--reuse-server", action="store_true")
    parser.add_argument("--keep-server", action="store_true")
    parser.add_argument("--server-temp", type=float, default=None, help="Optional startup --temp for rkllm3-server")
    parser.add_argument("--server-top-k", type=int, default=None, help="Optional startup --top-k for rkllm3-server")
    parser.add_argument("--server-top-p", type=float, default=None, help="Optional startup --top-p for rkllm3-server")
    parser.add_argument("--server-repeat-penalty", type=float, default=None, help="Optional startup --repeat-penalty for rkllm3-server")

    parser.add_argument("--llm-rknn")
    parser.add_argument("--llm-weight")
    parser.add_argument("--llm-vocab")
    parser.add_argument("--llm-embed")

    parser.add_argument("--prompt-file", help="Optional prompt template file containing {transcript}; embedded compact prompt is used if omitted")
    parser.add_argument("--response-format-json-object", dest="response_format_json_object", action="store_true", default=True)
    parser.add_argument("--no-response-format-json-object", dest="response_format_json_object", action="store_false")
    return parser


def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    proc: Optional[subprocess.Popen[Any]] = None
    result: Dict[str, Any] = {
        "status": "running",
        "input_mode": "audio-file" if args.audio_file else "transcript-file",
        "out_dir": str(out_dir),
    }

    try:
        transcript = load_transcript(args, out_dir)
        prompt_template, prompt_source = load_prompt_template(args)
        messages = build_messages(prompt_template, transcript)
        llm_files = discover_llm_files(args)

        server_log = out_dir / "server.log"
        proc = start_llm_server(args, llm_files, server_log)
        payload_preview = {
            "model": "qwen3-4b",
            "messages": messages,
            "max_tokens": args.max_tokens,
            "temperature": args.temperature,
        }
        if args.response_format_json_object:
            payload_preview["response_format"] = {"type": "json_object"}
        write_json(out_dir / "messages.json", messages)
        write_json(out_dir / "request.json", payload_preview)

        response = post_chat(args, messages)
        write_json(out_dir / "response_raw.json", response)
        content, finish_reason = get_response_content(response)
        write_text(out_dir / "response_content.txt", content)
        summary, schema_errors, used_json_extraction = parse_and_validate_content(content, finish_reason)
        write_json(out_dir / "summary.json", summary)

        result.update(
            {
                "status": "pass",
                "json_valid": True,
                "json_extracted_from_content": used_json_extraction,
                "schema_valid": True,
                "schema_errors": schema_errors,
                "finish_reason": finish_reason,
                "transcript_chars": len(transcript),
                "prompt_source": prompt_source,
                "model_dir": args.model_dir,
                "llm_files": {k: str(v) for k, v in llm_files.items()},
                "host": args.host,
                "port": args.port,
                "ctx": args.ctx,
                "predict": args.predict,
                "max_tokens": args.max_tokens,
                "elapsed_sec": round(time.time() - started, 3),
            }
        )
        write_json(out_dir / "result.json", result)
        print(f"PASS: {out_dir / 'result.json'}")
        return 0
    except ChainError as exc:
        result.update(
            {
                "status": "fail",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "exit_code": exc.exit_code,
                "elapsed_sec": round(time.time() - started, 3),
            }
        )
        write_json(out_dir / "result.json", result)
        print(f"FAIL: {exc}", file=sys.stderr)
        print(f"See: {out_dir / 'result.json'}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - top-level reporting
        result.update(
            {
                "status": "fail",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "exit_code": EXIT_RUNTIME,
                "elapsed_sec": round(time.time() - started, 3),
            }
        )
        write_json(out_dir / "result.json", result)
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"See: {out_dir / 'result.json'}", file=sys.stderr)
        return EXIT_RUNTIME
    finally:
        stop_llm_server(proc, args.keep_server)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = make_arg_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
