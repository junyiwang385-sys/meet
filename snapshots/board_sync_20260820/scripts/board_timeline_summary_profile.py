#!/usr/bin/env python3
"""Run identical RK1828 NPU meeting-summary pipelines for ASR and GT timelines."""

import argparse
import difflib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from board_meeting_chain_profile import (  # noqa: E402
    MemorySampler,
    discover_llm_files,
    log,
    post_chat,
    terminate_process,
    wait_ready,
    write_json,
)


DEFAULT_MODEL_DIR = "/userdata/meeting_agent/models/llm/v104/qwen2.5-7b-v104"
DEFAULT_SERVER = "/usr/bin/rkllm3-server"
DEFAULT_OUT_DIR = "/userdata/meeting_agent/output/timeline_summary_compare"
LINE_RE = re.compile(
    r"^\[(?P<index>\d+)\]"
    r"\[(?P<start>\d+:[0-5]\d(?:\.\d+)?)-(?P<end>\d+:[0-5]\d(?:\.\d+)?)\]"
    r"\[(?P<speaker>[^\]]+)\]\s*(?P<text>.*)$"
)
TOP_KEYS = {
    "title", "summary", "speakers", "topics", "actions",
    "questions", "risks", "key_points",
}

SYSTEM_PROMPT = """你是严格的中文会议纪要助手。只依据输入内容总结。
只输出一个合法 JSON 对象，不要 Markdown、代码块或解释。
不得编造负责人、截止时间、数字、决定或待办；不明确时写“未明确”。
普通讨论不能提升为决定或待办。可清理口头禅和明显转写噪声，但不得改变否定、条件、数量和因果关系。
refs 使用输入中的时间范围。"""

SCHEMA = """{
  "title": "一句话会议主题",
  "summary": "3到5句话总结",
  "speakers": [
    {"id": "说话人标签", "refs": "时间范围", "summary": "主要内容"}
  ],
  "topics": [
    {
      "name": "主题名称",
      "refs": "时间范围",
      "speakers": ["说话人标签"],
      "problem": "问题或现状，未明确则写未明确",
      "discussion": "讨论方案或观点",
      "decision": "明确决定，未明确则写未明确",
      "next": "后续工作，未明确则写未明确"
    }
  ],
  "actions": [
    {"task": "明确待办", "owner": "负责人或未明确", "deadline": "时间或未明确"}
  ],
  "questions": ["仍需确认的问题"],
  "risks": ["风险、限制或依赖项"],
  "key_points": ["重要讨论点"]
}"""

MAP_PROMPT = """请总结下面会议时间窗口的核心内容。
上下文只用于理解边界处语义，不得把只出现在上下文中的内容重复计入本窗口。
核心窗口：{core_start}-{core_end}
上下文范围：{context_start}-{context_end}
每个数组最多6项，没有内容时输出空数组。

JSON结构：
{schema}

时间线：
{timeline}
"""

REDUCE_PROMPT = """下面是同一场会议按固定时间窗口独立生成的中间纪要，已经按时间顺序排列。
请合并重复信息，生成一份紧凑的最终会议纪要。只能使用中间纪要已有信息，不得补充新事实；冲突或不明确的信息保持“未明确”。
普通讨论不能提升为决定或待办。删除跨窗口重复表述，不要逐窗口复述。
严格限制长度：summary 不超过250个汉字；speakers 最多8项，每项 summary 不超过80个汉字、refs 最多保留3个代表性时间范围；topics 最多6项，每个文本字段不超过80个汉字；actions、questions、risks、key_points 各最多6项，每项不超过60个汉字。

JSON结构：
{schema}

中间纪要：
{summaries}
"""


def parse_time(value):
    minutes, seconds = value.split(":", 1)
    return int(minutes) * 60.0 + float(seconds)


def format_time(seconds):
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:06.3f}"


def parse_timeline(path):
    path = pathlib.Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    rows = []
    for line_number, source_line in enumerate(raw.splitlines(), 1):
        line = source_line.strip()
        if not line:
            continue
        match = LINE_RE.fullmatch(line)
        if not match:
            raise ValueError(f"invalid timeline line {line_number}: {source_line[:200]}")
        start = parse_time(match.group("start"))
        end = parse_time(match.group("end"))
        if end <= start:
            raise ValueError(f"timeline end <= start at line {line_number}")
        speaker = re.sub(r"\(pred:[^)]+\)$", "", match.group("speaker")).strip()
        rows.append({
            "index": int(match.group("index")),
            "start": start,
            "end": end,
            "speaker": speaker,
            "text": re.sub(r"\s+", " ", match.group("text")).strip(),
        })
    if not rows:
        raise ValueError(f"empty timeline: {path}")
    rows.sort(key=lambda item: (item["start"], item["end"], item["index"]))
    stats = {
        "path": str(path),
        "utf8_bytes": len(raw.encode("utf-8")),
        "characters": len(raw),
        "lines": len(rows),
        "text_characters": sum(len(item["text"]) for item in rows),
        "start_seconds": round(rows[0]["start"], 3),
        "end_seconds": round(max(item["end"] for item in rows), 3),
        "speakers": sorted({item["speaker"] for item in rows}),
        "rough_token_range": {
            "lower": round(len(raw) * 0.7),
            "upper": round(len(raw) * 1.1),
        },
        "token_note": "rough_token_range仅用于运行前规划，实际token以rkllm3-server响应usage为准",
    }
    return rows, stats


def timeline_line(row):
    return (
        f"[{row['index']:04d}]"
        f"[{format_time(row['start'])}-{format_time(row['end'])}]"
        f"[{row['speaker']}] {row['text']}"
    ).rstrip()


def build_windows(meeting_end, core_seconds, margin_seconds):
    windows = []
    start = 0.0
    while start < meeting_end:
        end = min(start + core_seconds, meeting_end)
        windows.append({
            "index": len(windows),
            "core_start": start,
            "core_end": end,
            "context_start": max(0.0, start - margin_seconds),
            "context_end": min(meeting_end, end + margin_seconds),
        })
        start += core_seconds
    return windows


def core_window_index(row, core_seconds, last_index):
    midpoint = (row["start"] + row["end"]) / 2.0
    return min(int(midpoint // core_seconds), last_index)


def render_window(rows, windows, window, core_seconds):
    lines = []
    for row in rows:
        midpoint = (row["start"] + row["end"]) / 2.0
        assigned = core_window_index(row, core_seconds, len(windows) - 1)
        if assigned == window["index"]:
            lines.append(f"[核心] {timeline_line(row)}")
        elif window["context_start"] <= midpoint < window["context_end"]:
            lines.append(f"[上下文] {timeline_line(row)}")
    return "\n".join(lines) if lines else "[核心] 本窗口无转写内容"


def validate_summary(value):
    if not isinstance(value, dict) or set(value) != TOP_KEYS:
        return False, "top-level keys mismatch"
    if not isinstance(value["title"], str) or not isinstance(value["summary"], str):
        return False, "title/summary must be strings"
    expected_lists = ("speakers", "topics", "actions", "questions", "risks", "key_points")
    if any(not isinstance(value[key], list) for key in expected_lists):
        return False, "summary collection fields must be arrays"
    if any(len(value[key]) > 8 for key in expected_lists):
        return False, "summary collection exceeds item limit"
    for item in value["speakers"]:
        if not isinstance(item, dict) or set(item) != {"id", "refs", "summary"}:
            return False, "invalid speakers item"
    for item in value["topics"]:
        required = {"name", "refs", "speakers", "problem", "discussion", "decision", "next"}
        if not isinstance(item, dict) or set(item) != required or not isinstance(item["speakers"], list):
            return False, "invalid topics item"
    for item in value["actions"]:
        if not isinstance(item, dict) or set(item) != {"task", "owner", "deadline"}:
            return False, "invalid actions item"
    return True, None


def build_server_cmd(args, files):
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


def run_request(args, sampler, phase, out_dir, prompt, max_tokens):
    out_dir.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    payload = {
        "model": "default",
        "messages": messages,
        "temperature": args.temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    write_json(out_dir / "messages.json", messages)
    write_json(out_dir / "request.json", payload)
    sampler.set_phase(phase)
    started = time.time()
    try:
        raw, response = post_chat(args.host, args.port, payload, args.request_timeout)
        elapsed = round(time.time() - started, 3)
        (out_dir / "response.json").write_text(raw, encoding="utf-8")
        choice = response.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "").strip()
        result = {
            "status": "ok",
            "elapsed_seconds": elapsed,
            "finish_reason": choice.get("finish_reason"),
            "usage": response.get("usage"),
            "timings": response.get("timings"),
            "content_characters": len(content),
            "json_valid": False,
        }
        try:
            parsed = json.loads(content)
            valid, error = validate_summary(parsed)
            result["json_valid"] = valid
            result["json_error"] = error
            if valid:
                result["parsed"] = parsed
                write_json(out_dir / "summary.json", parsed)
        except Exception as exc:
            result["status"] = "invalid_json"
            result["json_error"] = repr(exc)
            result["content_tail"] = content[-1000:]
    except Exception as exc:
        result = {
            "status": "request_error",
            "elapsed_seconds": round(time.time() - started, 3),
            "json_valid": False,
            "error": repr(exc),
        }
    write_json(out_dir / "result.json", result)
    return result


def sum_usage(results):
    output = {"request_count": len(results), "elapsed_seconds": 0.0}
    usage_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    for key in usage_keys:
        values = [item.get("usage", {}).get(key) for item in results]
        values = [value for value in values if isinstance(value, (int, float))]
        output[f"{key}_sum"] = sum(values) if values else None
        output[f"{key}_max"] = max(values) if values else None
    output["elapsed_seconds"] = round(sum(item.get("elapsed_seconds", 0) for item in results), 3)
    return output


def run_timeline(kind, rows, stats, windows, args, root, sampler):
    kind_dir = root / kind
    request_dir = kind_dir / "requests"
    kind_dir.mkdir(parents=True, exist_ok=True)
    write_json(kind_dir / "input_stats.json", stats)
    (kind_dir / "canonical_timeline.txt").write_text(
        "\n".join(timeline_line(item) for item in rows) + "\n", encoding="utf-8"
    )

    map_results = []
    summaries = []
    for window in windows:
        prompt = MAP_PROMPT.format(
            core_start=format_time(window["core_start"]),
            core_end=format_time(window["core_end"]),
            context_start=format_time(window["context_start"]),
            context_end=format_time(window["context_end"]),
            schema=SCHEMA,
            timeline=render_window(rows, windows, window, args.core_window_seconds),
        )
        result = run_request(
            args, sampler, f"{kind}_map_{window['index']:02d}",
            request_dir / f"map_{window['index']:02d}", prompt, args.map_max_tokens,
        )
        map_results.append(result)
        log(
            f"[{kind.upper()} map {window['index'] + 1}/{len(windows)}] "
            f"valid={result.get('json_valid')} elapsed={result.get('elapsed_seconds')} usage={result.get('usage')}"
        )
        if not result.get("json_valid"):
            summary = {
                "status": "map_invalid",
                "input_stats": stats,
                "map_usage": sum_usage(map_results),
                "failed_window": window["index"],
            }
            write_json(kind_dir / "profile_summary.json", summary)
            return summary
        summaries.append({
            "core_window": f"{format_time(window['core_start'])}-{format_time(window['core_end'])}",
            "summary": result["parsed"],
        })

    write_json(kind_dir / "map_summaries.json", summaries)
    reduce_prompt = REDUCE_PROMPT.format(
        schema=SCHEMA,
        summaries=json.dumps(summaries, ensure_ascii=False, separators=(",", ":")),
    )
    reduce_result = run_request(
        args, sampler, f"{kind}_reduce", request_dir / "reduce",
        reduce_prompt, args.reduce_max_tokens,
    )
    log(
        f"[{kind.upper()} reduce] valid={reduce_result.get('json_valid')} "
        f"elapsed={reduce_result.get('elapsed_seconds')} usage={reduce_result.get('usage')}"
    )
    if reduce_result.get("json_valid"):
        write_json(kind_dir / "final_summary.json", reduce_result["parsed"])
    summary = {
        "status": "ok" if reduce_result.get("json_valid") else "reduce_invalid",
        "input_stats": stats,
        "map_usage": sum_usage(map_results),
        "reduce_usage": sum_usage([reduce_result]),
        "final_summary": reduce_result.get("parsed"),
    }
    write_json(kind_dir / "profile_summary.json", summary)
    return summary


def compare_summaries(asr, gt):
    fields = {}
    for key in sorted(TOP_KEYS):
        left = json.dumps(asr[key], ensure_ascii=False, sort_keys=True)
        right = json.dumps(gt[key], ensure_ascii=False, sort_keys=True)
        fields[key] = {
            "exact_match": asr[key] == gt[key],
            "text_similarity": round(difflib.SequenceMatcher(None, left, right).ratio(), 6),
        }
    return {
        "note": "该结果是确定性文本/结构差异，不替代人工语义评价。",
        "exact_match": asr == gt,
        "fields": fields,
    }


def prepare_out_dir(path, overwrite):
    out_dir = pathlib.Path(path).resolve()
    if out_dir == pathlib.Path(out_dir.anchor):
        raise ValueError("refusing filesystem root as out-dir")
    if out_dir.exists() and any(out_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"out-dir is not empty: {out_dir}; use --overwrite")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the same board NPU timeline-summary pipeline for ASR and GT."
    )
    parser.add_argument("--asr-timeline", required=True)
    parser.add_argument("--gt-timeline", required=True)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--order", choices=["asr-gt", "gt-asr"], default="asr-gt")

    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18232)
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--predict", type=int, default=1024)
    parser.add_argument("--map-max-tokens", type=int, default=512)
    parser.add_argument("--reduce-max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--server-temp", type=float, default=0.0)
    parser.add_argument("--server-top-k", type=int, default=1)
    parser.add_argument("--server-top-p", type=float, default=1.0)
    parser.add_argument("--server-repeat-penalty", type=float, default=1.05)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--request-timeout", type=int, default=1200)
    parser.add_argument("--core-window-seconds", type=float, default=300.0)
    parser.add_argument("--context-margin-seconds", type=float, default=30.0)
    parser.add_argument("--sample-interval", type=float, default=0.2)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.predict < max(args.map_max_tokens, args.reduce_max_tokens):
        raise ValueError("predict must cover map/reduce max tokens")

    asr_rows, asr_stats = parse_timeline(args.asr_timeline)
    gt_rows, gt_stats = parse_timeline(args.gt_timeline)
    meeting_end = max(asr_stats["end_seconds"], gt_stats["end_seconds"])
    windows = build_windows(meeting_end, args.core_window_seconds, args.context_margin_seconds)
    out_dir = prepare_out_dir(args.out_dir, args.overwrite)
    write_json(out_dir / "run_config.json", vars(args))
    write_json(out_dir / "input_stats.json", {"asr": asr_stats, "gt": gt_stats})
    write_json(out_dir / "shared_windows.json", windows)

    files = discover_llm_files(args.model_dir)
    cmd = build_server_cmd(args, files)
    write_json(out_dir / "llm_cmd.json", cmd)
    sampler = MemorySampler(out_dir / "memory_samples.jsonl", args.sample_interval)
    sampler.start()
    proc = None
    server_log = None
    run_summary = {"status": "unknown", "order": args.order, "results": {}}
    try:
        sampler.set_phase("llm_server_start")
        server_log = open(out_dir / "rkllm_server.log", "wb")
        proc = subprocess.Popen(cmd, stdout=server_log, stderr=subprocess.STDOUT)
        sampler.add_target("rkllm_server", proc.pid)
        ready = wait_ready(args.host, args.port, args.ready_timeout)
        run_summary["server_ready_seconds"] = ready
        if ready is None:
            run_summary["status"] = "server_not_ready"
            return 2

        data = {
            "asr": (asr_rows, asr_stats),
            "gt": (gt_rows, gt_stats),
        }
        for kind in args.order.split("-"):
            rows, stats = data[kind]
            log(
                f"[{kind.upper()}] chars={stats['characters']} bytes={stats['utf8_bytes']} "
                f"rough_tokens={stats['rough_token_range']}"
            )
            run_summary["results"][kind] = run_timeline(
                kind, rows, stats, windows, args, out_dir, sampler
            )

        asr_result = run_summary["results"]["asr"]
        gt_result = run_summary["results"]["gt"]
        if asr_result["status"] == "ok" and gt_result["status"] == "ok":
            comparison = compare_summaries(asr_result["final_summary"], gt_result["final_summary"])
            write_json(out_dir / "summary_comparison.json", comparison)
            run_summary["comparison"] = comparison
            run_summary["status"] = "ok"
            return 0
        run_summary["status"] = "summary_invalid"
        return 5
    except Exception as exc:
        run_summary["status"] = "error"
        run_summary["error"] = repr(exc)
        log(f"[ERROR] {repr(exc)}")
        return 1
    finally:
        sampler.set_phase("cleanup")
        if proc is not None:
            terminate_process(proc)
        if server_log is not None:
            server_log.close()
        sampler.stop()
        memory = sampler.summary()
        run_summary["memory"] = memory
        write_json(out_dir / "memory_summary.json", memory)
        write_json(out_dir / "run_summary.json", run_summary)
        log(f"[DONE] status={run_summary['status']} out={out_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
