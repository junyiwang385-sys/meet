#!/usr/bin/env python3
"""Measure RKLLM prompt usage, request latency, and memory peak on the board."""

import argparse
import json
import pathlib
import threading
import time
import urllib.request


def read_meminfo():
    result = {}
    with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(("MemTotal:", "MemAvailable:")):
                key, value, *_ = line.split()
                result[key.rstrip(":")] = int(value)
    return result


def read_proc_status(pid):
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


def find_server_pid(port):
    matches = []
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        args = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if not args or "rkllm3-server" not in pathlib.Path(args[0]).name:
            continue
        for index, value in enumerate(args[:-1]):
            if value == "--port" and args[index + 1] == str(port):
                matches.append(int(entry.name))
    if len(matches) != 1:
        raise RuntimeError(f"expected one rkllm3-server on port {port}, found: {matches}")
    return matches[0]


def kb_to_mb(value):
    return round(value / 1024.0, 3) if value is not None else None


def parse_args():
    parser = argparse.ArgumentParser(description="Profile one full-timeline RKLLM request.")
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--pid", type=int, help="rkllm3-server PID; auto-detected from --port by default")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--sample-interval", type=float, default=0.05)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--label", default="rkllm_context_probe")
    return parser.parse_args()


def main():
    args = parse_args()
    timeline_path = pathlib.Path(args.timeline)
    timeline = timeline_path.read_text(encoding="utf-8", errors="replace")
    pid = args.pid or find_server_pid(args.port)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_path = out_dir / "memory_samples.jsonl"
    response_path = out_dir / "response.json"
    report_path = out_dir / "memory_probe_summary.json"

    stop = threading.Event()
    samples = []

    def sample_once():
        mem = read_meminfo()
        proc = read_proc_status(pid)
        total = mem.get("MemTotal")
        available = mem.get("MemAvailable")
        return {
            "timestamp": round(time.time(), 6),
            "mem_total_kb": total,
            "mem_available_kb": available,
            "board_used_kb": total - available if total is not None and available is not None else None,
            "process_rss_kb": proc.get("VmRSS"),
            "process_hwm_kb": proc.get("VmHWM"),
            "process_vmsize_kb": proc.get("VmSize"),
        }

    def sampler():
        with samples_path.open("w", encoding="utf-8") as fh:
            while not stop.is_set():
                item = sample_once()
                samples.append(item)
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
                fh.flush()
                stop.wait(args.sample_interval)

    payload = {
        "model": "default",
        "messages": [{
            "role": "user",
            "content": (
                "请根据下面的完整会议时间线生成简洁会议总结，包括会议主题、"
                "主要讨论内容和关键事项。只依据输入内容，不要编造。\n\n" + timeline
            ),
        }],
        "temperature": 0,
        "max_tokens": args.max_tokens,
    }

    baseline = sample_once()
    thread = threading.Thread(target=sampler, daemon=True)
    thread.start()
    started = time.time()
    response = None
    error = None
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{args.port}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1800) as result:
            response = json.loads(result.read().decode("utf-8", "replace"))
        response_path.write_text(
            json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        error = repr(exc)
    finally:
        stop.set()
        thread.join()
        samples.append(sample_once())

    board_used = [item["board_used_kb"] for item in samples if item["board_used_kb"] is not None]
    available = [item["mem_available_kb"] for item in samples if item["mem_available_kb"] is not None]
    rss = [item["process_rss_kb"] for item in samples if item["process_rss_kb"] is not None]
    hwm = [item["process_hwm_kb"] for item in samples if item["process_hwm_kb"] is not None]
    vmsize = [item["process_vmsize_kb"] for item in samples if item["process_vmsize_kb"] is not None]

    choice = response.get("choices", [{}])[0] if response else {}
    report = {
        "label": args.label,
        "timeline": str(timeline_path),
        "timeline_lines": len(timeline.splitlines()),
        "timeline_characters": len(timeline),
        "timeline_utf8_bytes": len(timeline.encode("utf-8")),
        "server_port": args.port,
        "server_pid": pid,
        "requested_max_tokens": args.max_tokens,
        "sample_interval_seconds": args.sample_interval,
        "sample_count": len(samples),
        "request_elapsed_seconds": round(time.time() - started, 3),
        "usage": response.get("usage") if response else None,
        "timings": response.get("timings") if response else None,
        "finish_reason": choice.get("finish_reason"),
        "response_characters": len(choice.get("message", {}).get("content", "")),
        "baseline_board_used_mb": kb_to_mb(baseline.get("board_used_kb")),
        "board_used_peak_mb": kb_to_mb(max(board_used)) if board_used else None,
        "request_peak_delta_mb": (
            kb_to_mb(max(board_used) - baseline["board_used_kb"])
            if board_used and baseline.get("board_used_kb") is not None else None
        ),
        "mem_available_before_mb": kb_to_mb(baseline.get("mem_available_kb")),
        "mem_available_min_mb": kb_to_mb(min(available)) if available else None,
        "process_rss_peak_mb": kb_to_mb(max(rss)) if rss else None,
        "process_hwm_peak_mb": kb_to_mb(max(hwm)) if hwm else None,
        "process_vmsize_peak_mb": kb_to_mb(max(vmsize)) if vmsize else None,
        "error": error,
        "outputs": {
            "response": str(response_path),
            "memory_samples": str(samples_path),
            "summary": str(report_path),
        },
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
