#!/usr/bin/env python3
import argparse
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request


REQUIRED_SUFFIXES = {
    "model": ".rknn",
    "weight": ".weight",
    "vocab": ".tokenizer.gguf",
    "embed": ".embed.bin",
}


def find_file(model_dir, suffix):
    matches = sorted(pathlib.Path(model_dir).glob(f"*{suffix}"))
    return str(matches[0]) if matches else None


def discover_model_dirs(root):
    root = pathlib.Path(root)
    dirs = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        files = {name: find_file(path, suffix) for name, suffix in REQUIRED_SUFFIXES.items()}
        if all(files.values()):
            dirs.append(path)
    return dirs


def wait_ready(port, timeout_s):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).read()
            return True
        except Exception:
            time.sleep(1)
    return False


def post_chat(port, prompt, max_tokens, temperature):
    req = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    data = json.dumps(req, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    raw = urllib.request.urlopen(request, timeout=600).read().decode("utf-8", "replace")
    elapsed = time.time() - started
    return elapsed, json.loads(raw)


def looks_sane(text):
    if not text or len(text.strip()) < 5:
        return False, "empty_or_too_short"
    bad_fragments = ["construct", "processor", "GUID", "_SEGMENT"]
    if any(fragment in text for fragment in bad_fragments):
        return False, "known_garbage_fragment"
    chinese = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if chinese < 4:
        return False, "too_few_chinese_chars"
    return True, "ok"


def run_one(args, model_dir, index):
    model_dir = pathlib.Path(model_dir)
    files = {name: find_file(model_dir, suffix) for name, suffix in REQUIRED_SUFFIXES.items()}
    missing = [name for name, value in files.items() if not value]
    result = {
        "model_dir": str(model_dir),
        "model_name": model_dir.name,
        "status": "unknown",
        "missing": missing,
    }
    if missing:
        result["status"] = "missing_files"
        return result

    port = args.port_base + index
    log_path = args.out_dir / f"{model_dir.name}.server.log"
    cmd = [
        args.server,
        "-m",
        files["model"],
        "--weight",
        files["weight"],
        "--vocab",
        files["vocab"],
        "--embed",
        files["embed"],
        "-c",
        str(args.ctx),
        "-n",
        str(args.predict),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    log = open(log_path, "wb")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    try:
        ready_started = time.time()
        if not wait_ready(port, args.ready_timeout):
            result["status"] = "server_not_ready"
            return result
        result["ready_seconds"] = round(time.time() - ready_started, 3)

        elapsed, response = post_chat(port, args.prompt, args.max_tokens, args.temperature)
        choice = response.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        sane, sane_reason = looks_sane(content)
        result.update(
            {
                "status": "pass" if sane else "bad_output",
                "sane_reason": sane_reason,
                "elapsed_seconds": round(elapsed, 3),
                "finish_reason": choice.get("finish_reason"),
                "usage": response.get("usage"),
                "timings": response.get("timings"),
                "content": content,
            }
        )
        return result
    except Exception as exc:
        result["status"] = "error"
        result["error"] = repr(exc)
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/userdata", help="Root to scan for model dirs")
    parser.add_argument("--model-dir", action="append", default=[], help="Explicit model dir; can repeat")
    parser.add_argument("--out-dir", default="/tmp/rkllm_smoke")
    parser.add_argument("--server", default="/usr/bin/rkllm3-server")
    parser.add_argument("--ctx", type=int, default=2048)
    parser.add_argument("--predict", type=int, default=128)
    parser.add_argument("--max-tokens", type=int, default=96)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--port-base", type=int, default=18200)
    parser.add_argument("--ready-timeout", type=int, default=120)
    parser.add_argument(
        "--prompt",
        default="请用中文简短回答：你能帮助整理中文会议纪要吗？请回答两句话。",
    )
    args = parser.parse_args()
    args.out_dir = pathlib.Path(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    model_dirs = [pathlib.Path(p) for p in args.model_dir]
    if not model_dirs:
        model_dirs = discover_model_dirs(args.root)

    results = []
    for index, model_dir in enumerate(model_dirs):
        print(f"==> testing {model_dir}", flush=True)
        result = run_one(args, model_dir, index)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        results.append(result)

    summary_path = args.out_dir / "summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(1 for item in results if item.get("status") == "pass")
    print(f"summary: {passed}/{len(results)} passed")
    print(f"summary_file: {summary_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
