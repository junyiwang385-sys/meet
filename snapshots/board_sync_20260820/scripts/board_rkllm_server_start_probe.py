#!/usr/bin/env python3
"""Start rkllm3-server, wait for health, and record setup diagnostics."""

import argparse
import json
import pathlib
import re
import signal
import subprocess
import time
import urllib.request


SUFFIXES = {
    "model": ".rknn",
    "weight": ".weight",
    "vocab": ".tokenizer.gguf",
    "embed": ".embed.bin",
}
LOG_PATTERN = re.compile(
    r"ctx-size|max_context_len|limited|n_ctx_slot|MODEL_SETUP|create_mem|timeout|ERROR_PIPE|NPUTransfer",
    flags=re.IGNORECASE,
)


def find_one(model_dir, suffix):
    matches = sorted(pathlib.Path(model_dir).glob(f"*{suffix}"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one *{suffix} in {model_dir}, found: {matches}")
    return str(matches[0])


def read_meminfo():
    result = {}
    wanted = {"MemTotal", "MemAvailable", "CmaTotal", "CmaFree"}
    with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            key, value, *_ = line.split()
            key = key.rstrip(":")
            if key in wanted:
                result[key] = int(value)
    return result


def read_status(pid):
    result = {}
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith(("VmRSS:", "VmHWM:", "VmSize:")):
                    key, value, *_ = line.split()
                    result[key.rstrip(":")] = int(value)
    except OSError:
        pass
    return result


def kb_to_mb(value):
    return round(value / 1024.0, 3) if value is not None else None


def healthy(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def stop_process(proc):
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def parse_args():
    parser = argparse.ArgumentParser(description="Probe RKLLM server MODEL_SETUP and context configuration.")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--ctx", type=int, required=True)
    parser.add_argument("--predict", type=int, default=512)
    parser.add_argument("--port", type=int, default=18246)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--server", default="/usr/bin/rkllm3-server")
    parser.add_argument("--keep-running", action="store_true", help="Leave a healthy server running after the probe")
    return parser.parse_args()


def main():
    args = parse_args()
    model_dir = pathlib.Path(args.model_dir)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "rkllm_server.log"
    summary_path = out_dir / "server_start_probe.json"
    pid_path = out_dir / "rkllm_server.pid"

    files = {name: find_one(model_dir, suffix) for name, suffix in SUFFIXES.items()}
    cmd = [
        args.server,
        "-m", files["model"],
        "--weight", files["weight"],
        "--vocab", files["vocab"],
        "--embed", files["embed"],
        "-c", str(args.ctx),
        "-n", str(args.predict),
        "--temp", "0",
        "--top-k", "1",
        "--top-p", "1",
        "--repeat-penalty", "1.05",
        "--host", "127.0.0.1",
        "--port", str(args.port),
    ]
    (out_dir / "server_cmd.json").write_text(
        json.dumps(cmd, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    memory_before = read_meminfo()
    started = time.time()
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        pid_path.write_text(str(proc.pid) + "\n", encoding="utf-8")
        print(f"server_pid={proc.pid}", flush=True)
        ready = False
        for second in range(1, args.timeout + 1):
            if healthy(args.port):
                ready = True
                print(f"server_ready after {second}s", flush=True)
                break
            if proc.poll() is not None:
                print(f"server_exited rc={proc.returncode}", flush=True)
                break
            if second % 10 == 0:
                print(f"waiting {second}s...", flush=True)
            time.sleep(1)

        elapsed = round(time.time() - started, 3)
        memory_after = read_meminfo()
        process_memory = read_status(proc.pid)
        log_file.flush()

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    context_lines = [line for line in log_text.splitlines() if LOG_PATTERN.search(line)]
    summary = {
        "status": "ready" if ready else "failed_or_timeout",
        "model_dir": str(model_dir),
        "files": files,
        "ctx_requested": args.ctx,
        "predict": args.predict,
        "port": args.port,
        "pid": proc.pid,
        "return_code": proc.poll(),
        "elapsed_seconds": elapsed,
        "memory_before_kb": memory_before,
        "memory_after_kb": memory_after,
        "mem_available_delta_mb": kb_to_mb(
            memory_before.get("MemAvailable", 0) - memory_after.get("MemAvailable", 0)
        ),
        "process_memory_mb": {key: kb_to_mb(value) for key, value in process_memory.items()},
        "context_log_lines": context_lines[-100:],
        "log": str(log_path),
        "kept_running": bool(ready and args.keep_running),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if not ready:
        print("===== log tail =====", flush=True)
        print("\n".join(log_text.splitlines()[-100:]), flush=True)
    if proc.poll() is None and not (ready and args.keep_running):
        stop_process(proc)
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
