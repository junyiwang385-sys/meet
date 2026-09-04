"""开发期聚合报告：把一次 harness 运行的产物汇成一份可读+可对比的优化报告。

用途：测试开发阶段把板端产物拷回 PC 后，对着 out-dir 生成 run_report.md / run_report.json，
系统化沉淀分段/摘要/重试/token/时延等优化相关指标，并自动打优化红旗，供后续调参对比。

只用标准库；对缺失文件健壮（缺就填 None / "N/A"，不崩）。
"""

from __future__ import annotations

import json
import pathlib
import statistics
from typing import Any


# 目标/阈值（用于自动红旗；与 product_summary 的软约束对齐，改动时同步）
TARGET_BLOCK_SUMMARY_CHARS = 120
TARGET_OVERVIEW_CHARS = 300
RETRY_RATE_WARN = 0.15
CONFIGURED_CHARS_PER_TOKEN = 1.3
CHARS_PER_TOKEN_DRIFT_WARN = 0.2
SCHEMA_ARRAY_FIELDS = (
    "chapters", "speakers", "key_points", "decisions", "action_items",
    "open_questions", "risks", "keywords",
)


def _load(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _short_err(err: Any) -> Any:
    if err is None:
        return None
    text = err if isinstance(err, str) else json.dumps(err, ensure_ascii=False)
    return text[:300]


def _stats(values: list[float]) -> dict[str, Any]:
    values = [v for v in values if v is not None]
    if not values:
        return {"count": 0, "min": None, "avg": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "avg": round(statistics.mean(values), 1),
        "max": max(values),
    }


def _messages_chars(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    return sum(len(str(m.get("content") or "")) for m in messages if isinstance(m, dict))


def _kind_from_dir(request_dir: pathlib.Path, llm_dir: pathlib.Path) -> str:
    rel = request_dir.relative_to(llm_dir).as_posix()
    if rel.startswith("blocks/"):
        return "block-summary"
    if rel.startswith("requests/full_summary"):
        return "full-summary"
    if rel.startswith("requests/action_review"):
        return "action-review"
    if rel.startswith("requests/speaker_batches"):
        return "speaker-batch"
    return "other"


def _iter_request_dirs(llm_dir: pathlib.Path) -> list[pathlib.Path]:
    if not llm_dir.is_dir():
        return []
    return sorted(p.parent for p in llm_dir.rglob("status.json"))


def build_run_report(root: pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root)
    llm_dir = root / "03_llm_summary"
    manifest = _load(root / "run_manifest.json") or {}
    stage_status = _load(root / "stage_status.json") or {}
    metrics = _load(root / "run_metrics.json") or {}
    plan = _load(llm_dir / "plan.json") or {}
    segmentation = _load(llm_dir / "segmentation.json") or {}
    chapters = _load(llm_dir / "chapters.json") or []
    full_summary = _load(llm_dir / "full_summary.json") or {}
    meeting_summary = _load(root / "meeting_summary.json") or {}
    meeting_result = _load(root / "meeting_result.json") or {}

    # 身份与配置
    identity = manifest.get("identity", {})
    config = manifest.get("config", {})
    duration_ms = ((meeting_result.get("meeting") or {}).get("duration_ms"))
    report: dict[str, Any] = {
        "identity": {
            "run_id": identity.get("run_id"),
            "harness_version": manifest.get("harness_version"),
            "product_summary_version": plan.get("version"),
            "segmentation_version": segmentation.get("version"),
            "source_audio_seconds": round(duration_ms / 1000, 1) if duration_ms else None,
        },
        "config": {k: config.get(k) for k in (
            "ctx", "predict", "max_tokens", "input_safety_tokens",
            "input_chars_per_token", "temperature", "resume",
        )},
    }

    # 时延
    stages = stage_status.get("stages", {}) or {}
    report["timing"] = {
        "status": stage_status.get("status"),
        "total_seconds": metrics.get("total_elapsed_seconds"),
        "stage_seconds": {
            name: info.get("elapsed_seconds") for name, info in stages.items()
        },
    }
    # 各 stage 的 status/error 进结构化日志（失败原因也在此，无需另回传 stage_status.json）
    report["stages_detail"] = {
        name: {
            "status": (info or {}).get("status"),
            "reason": (info or {}).get("reason"),
            "error": _short_err((info or {}).get("error")),
        }
        for name, info in stages.items()
    }

    # A 层分段
    blocks_meta = segmentation.get("blocks", []) or []
    speaker_open = sum(1 for b in blocks_meta if "speaker" in (b.get("opened_by") or []))
    report["segmentation"] = {
        "policy": plan.get("policy"),
        "block_count": plan.get("block_count") or segmentation.get("block_count"),
        "chapter_count": plan.get("chapter_count") or (len(chapters) or None),
        "boundary_reason_counts": segmentation.get("boundary_reason_counts"),
        "blocks_opened_by_speaker": speaker_open,
        "block_text_chars": _stats([b.get("text_chars") for b in blocks_meta]),
        "block_segment_count": _stats([b.get("segment_count") for b in blocks_meta]),
        "config": segmentation.get("config"),
    }

    # B 层块（最终结果）
    block_dirs = sorted((llm_dir / "blocks").glob("blk-*")) if (llm_dir / "blocks").is_dir() else []
    block_summ_lens: list[int] = []
    continues = 0
    retried_blocks: list[str] = []
    for bd in block_dirs:
        vb = _load(bd / "validated_block.json") or {}
        if vb.get("summary"):
            block_summ_lens.append(len(vb["summary"]))
        if vb.get("continues_previous"):
            continues += 1
        if (bd / "attempt-2").is_dir():
            retried_blocks.append(bd.name)
    report["blocks"] = {
        "count": len(block_dirs),
        "summary_chars": _stats(block_summ_lens),
        "continues_previous_count": continues,
        "retried_block_ids": retried_blocks,
    }

    # reduce 与最终纪要
    overview_text = (full_summary.get("overview") or {})
    if isinstance(overview_text, dict):
        overview_len = len(overview_text.get("text") or "")
    else:
        overview_len = 0
    empty_fields = [
        f for f in SCHEMA_ARRAY_FIELDS
        if isinstance(meeting_summary.get(f), list) and not meeting_summary.get(f)
    ]
    report["reduce"] = {
        "overview_source": plan.get("overview_source"),
        "overview_chars": overview_len,
        "chapter_summary_chars": _stats([len(c.get("overview") or "") for c in chapters]),
        "speaker_count": plan.get("speaker_count"),
        "action_candidates": plan.get("action_candidate_count"),
        "action_items_final": len(meeting_summary.get("action_items") or []),
        "empty_schema_fields": empty_fields,
    }

    # LLM 经济学：遍历所有请求目录，聚合 usage / thinking / prompt 字符（校准 chars_per_token）
    llm_metrics = metrics.get("llm", {}) or (metrics.get("runtime", {}) or {}).get("llm", {}) or {}
    total_prompt_tok = total_completion_tok = total_prompt_chars = 0
    thinking_by_kind: dict[str, list[int]] = {}
    finish_reasons: dict[str, int] = {}
    for rd in _iter_request_dirs(llm_dir):
        kind = _kind_from_dir(rd, llm_dir)
        status = _load(rd / "status.json") or {}
        usage = status.get("usage") or {}
        total_prompt_tok += int(usage.get("prompt_tokens") or 0)
        total_completion_tok += int(usage.get("completion_tokens") or 0)
        fr = status.get("finish_reason")
        if fr:
            finish_reasons[fr] = finish_reasons.get(fr, 0) + 1
        th = rd / "thinking.txt"
        if th.is_file():
            thinking_by_kind.setdefault(kind, []).append(len(th.read_text(encoding="utf-8")))
        msgs = _load(rd / "messages.json")
        total_prompt_chars += _messages_chars(msgs)
    actual_cpt = round(total_prompt_chars / total_prompt_tok, 3) if total_prompt_tok else None
    report["llm_economics"] = {
        "counts": {k: llm_metrics.get(k) for k in (
            "request_count", "transport_request_count", "validation_failed_count",
            "retry_count", "split_count", "reused_request_count",
        )},
        "total_prompt_tokens": total_prompt_tok,
        "total_completion_tokens": total_completion_tok,
        "finish_reasons": finish_reasons,
        "thinking_chars_by_kind": {k: _stats(v) for k, v in thinking_by_kind.items()},
        "chars_per_token_actual": actual_cpt,
        "chars_per_token_configured": config.get("input_chars_per_token", CONFIGURED_CHARS_PER_TOKEN),
    }

    # 质量
    quality = meeting_result.get("quality") or {}
    report["quality"] = {
        "status": quality.get("status"),
        "warnings": quality.get("warnings"),
        "weak_chapters": quality.get("weak_chapters"),
    }

    # 内容丰富（enrichment）：直接读 enrichment.json，不靠人工数
    enrichment = _load(llm_dir / "enrichment.json") or {}
    quotes = enrichment.get("quotes") or []
    report["enrichment"] = {
        "present": bool(enrichment),
        "keywords": len(enrichment.get("keywords") or []),
        "qa": len(enrichment.get("qa") or []),
        "quotes": len(quotes),
        "quotes_verbatim": sum(1 for q in quotes if isinstance(q, dict) and q.get("verbatim")),
        "decisions": len(enrichment.get("decisions") or []),
        "has_outline": bool(enrichment.get("outline_summary")),
    }

    # 内存峰值 + 泄漏判定：读 runtime/memory_summary.json（键名跨采样器可能不同，多候选 + 存原始键）
    mem = _load(root / "runtime" / "memory_summary.json") or {}

    def _mm(*names: str) -> Any:
        for name in names:
            if isinstance(mem, dict) and name in mem:
                return mem[name]
        return None

    # server 峰值在嵌套 process_peaks.rkllm_server 里（板端采样器实际结构）
    server_rss = _mm("server_rss_peak_mb", "peak_server_rss_mb")
    if server_rss is None:
        proc_peaks = mem.get("process_peaks") if isinstance(mem, dict) else None
        if isinstance(proc_peaks, dict):
            server_rss = (proc_peaks.get("rkllm_server") or {}).get("rss_peak_mb")

    # 泄漏判定：板端不直接产出，用「cleanup 相位峰值 - 基线」的残留量推导。
    # 残留含页缓存等正常开销，阈值放宽到 500MB；缺相位数据则保持 None（不误报）。
    leak = _mm("memory_leak_suspected")
    if leak is None:
        phases = mem.get("phase_board_used_peak_mb") if isinstance(mem, dict) else None
        baseline = _mm("baseline_board_used_mb")
        if isinstance(phases, dict) and isinstance(baseline, (int, float)):
            cleanup_peak = phases.get("llm_cleanup")
            if isinstance(cleanup_peak, (int, float)):
                leak = (cleanup_peak - baseline) > 500.0

    report["memory"] = {
        "board_used_peak_mb": _mm("board_used_peak_mb", "peak_board_used_mb", "board_peak_mb"),
        "board_used_peak_delta_mb": _mm("board_used_peak_delta_mb"),
        "baseline_board_used_mb": _mm("baseline_board_used_mb"),
        "server_rss_peak_mb": server_rss,
        "mem_available_min_mb": _mm("mem_available_min_mb", "min_mem_available_mb"),
        "memory_leak_suspected": leak,
        "raw_keys": sorted(mem.keys()) if isinstance(mem, dict) else None,
    }

    # server 启动：本设计每次运行仅一个 rkllm server（pipeline 持有、摘要+enrichment 复用）；
    # ready_seconds 有单值 + 只有一个 rkllm_server.log 即证"只加载一次"。
    llm_rt = (meeting_result.get("runtime") or {}).get("llm") or {}
    server_log = llm_dir / "rkllm_server.log"
    llm_cmd = llm_dir / "llm_cmd.json"
    # 「只加载一次」的格式无关证据：单个 rkllm_server.log + 单个 llm_cmd.json + ready_seconds 单值。
    # start() 幂等且写 llm_cmd.json 仅在真正 spawn 时发生；摘要+enrichment 共用同一 session/out_dir，
    # 若 enrichment 另起 server 会产生第二处 spawn 证据。强证可回传 memory_samples.jsonl 数 llm_server_start 相位。
    report["server"] = {
        "ready_seconds": llm_rt.get("server_ready_seconds"),
        "log_present": server_log.is_file(),
        "log_size_bytes": server_log.stat().st_size if server_log.is_file() else None,
        "llm_cmd_present": llm_cmd.is_file(),
        "loaded_once": bool(server_log.is_file() and llm_cmd.is_file() and llm_rt.get("server_ready_seconds") is not None),
    }

    report["flags"] = _optimization_flags(report)
    return report


def _optimization_flags(report: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    seg = report["segmentation"]
    blocks = report["blocks"]
    reduce = report["reduce"]
    econ = report["llm_economics"]

    avg_summary = blocks["summary_chars"].get("avg")
    if avg_summary is not None and avg_summary < TARGET_BLOCK_SUMMARY_CHARS:
        flags.append(f"块摘要偏短：均 {avg_summary} 字 < 目标 {TARGET_BLOCK_SUMMARY_CHARS}")

    if reduce["overview_chars"] and reduce["overview_chars"] < TARGET_OVERVIEW_CHARS:
        flags.append(f"overview 偏短：{reduce['overview_chars']} 字 < 目标 {TARGET_OVERVIEW_CHARS}")
    if reduce["overview_source"] == "chapter_summaries":
        flags.append("overview 走了有损章节归并（未接地原文）")

    bc, cc = seg.get("block_count"), seg.get("chapter_count")
    if bc and cc and cc > bc * 0.7:
        flags.append(f"合并率低：{bc} 块仅并到 {cc} 章（continues_previous 合并偏保守）")
    if seg.get("blocks_opened_by_speaker") and bc and seg["blocks_opened_by_speaker"] > bc * 0.5:
        flags.append(f"speaker 假边界多：{seg['blocks_opened_by_speaker']}/{bc} 块由换人开启（过切嫌疑）")

    # think 未关：抽取类仍有 thinking
    for kind in ("block-summary", "full-summary", "speaker-batch"):
        st = econ["thinking_chars_by_kind"].get(kind)
        if st and st.get("avg"):
            flags.append(f"think 未关：{kind} 仍在思考（均 {st['avg']} 字/次），应 /no_think")

    counts = econ["counts"]
    req, retry = counts.get("request_count"), counts.get("retry_count")
    if req and retry and retry / req > RETRY_RATE_WARN:
        flags.append(f"重试率偏高：{retry}/{req} = {round(100*retry/req)}%")

    act, cfg = econ["chars_per_token_actual"], econ["chars_per_token_configured"]
    if act and cfg and abs(act - cfg) > CHARS_PER_TOKEN_DRIFT_WARN:
        flags.append(f"chars_per_token 需校准：实测 {act} vs 配置 {cfg}（预算估算偏差）")

    if reduce["empty_schema_fields"]:
        flags.append(f"空 schema 字段：{', '.join(reduce['empty_schema_fields'])}（未抽取）")

    enr = report.get("enrichment") or {}
    if enr.get("present") and not enr.get("has_outline"):
        flags.append("enrichment 缺 outline_summary（层级大纲未产出）")
    if (report.get("memory") or {}).get("memory_leak_suspected"):
        flags.append("疑似内存泄漏（memory_summary 判定）")

    return flags


def render_markdown(report: dict[str, Any]) -> str:
    ident = report["identity"]
    lines = [
        f"# 运行聚合报告 · {ident.get('run_id') or 'unknown'}",
        "",
        f"- 版本：harness {ident.get('harness_version')} / "
        f"summary {ident.get('product_summary_version')} / seg {ident.get('segmentation_version')}",
        f"- 音频时长：{ident.get('source_audio_seconds')} s",
        f"- 配置：{json.dumps(report['config'], ensure_ascii=False)}",
        "",
        "## 🚩 优化红旗",
    ]
    flags = report["flags"]
    lines += [f"- {f}" for f in flags] if flags else ["- （无）"]

    t = report["timing"]
    lines += [
        "",
        "## ⏱ 时延",
        f"- 状态 {t['status']}，总 {t['total_seconds']} s",
        f"- 各阶段：{json.dumps(t['stage_seconds'], ensure_ascii=False)}",
        "",
        "## ✂️ 分段（A 层）",
        f"- policy={report['segmentation']['policy']}  "
        f"块 {report['segmentation']['block_count']} → 章 {report['segmentation']['chapter_count']}",
        f"- 边界理由：{json.dumps(report['segmentation']['boundary_reason_counts'], ensure_ascii=False)}",
        f"- 换人开启的块：{report['segmentation']['blocks_opened_by_speaker']}",
        f"- 块字数：{json.dumps(report['segmentation']['block_text_chars'], ensure_ascii=False)}",
        f"- 块段数：{json.dumps(report['segmentation']['block_segment_count'], ensure_ascii=False)}",
        f"- seg 配置：{json.dumps(report['segmentation']['config'], ensure_ascii=False)}",
        "",
        "## 📝 块摘要（B 层）",
        f"- 块数 {report['blocks']['count']}，continues_previous {report['blocks']['continues_previous_count']}",
        f"- 摘要字数：{json.dumps(report['blocks']['summary_chars'], ensure_ascii=False)}",
        f"- 重试的块：{report['blocks']['retried_block_ids']}",
        "",
        "## 🧵 归并与纪要（C 层）",
        f"- overview 来源 {report['reduce']['overview_source']}，字数 {report['reduce']['overview_chars']}",
        f"- 章节摘要字数：{json.dumps(report['reduce']['chapter_summary_chars'], ensure_ascii=False)}",
        f"- 发言人 {report['reduce']['speaker_count']}，待办 {report['reduce']['action_candidates']}→{report['reduce']['action_items_final']}",
        f"- 空字段：{report['reduce']['empty_schema_fields']}",
        "",
        "## 💰 LLM 经济学",
        f"- 计数：{json.dumps(report['llm_economics']['counts'], ensure_ascii=False)}",
        f"- token：prompt {report['llm_economics']['total_prompt_tokens']} / "
        f"completion {report['llm_economics']['total_completion_tokens']}",
        f"- finish_reason：{json.dumps(report['llm_economics']['finish_reasons'], ensure_ascii=False)}",
        f"- thinking/次：{json.dumps(report['llm_economics']['thinking_chars_by_kind'], ensure_ascii=False)}",
        f"- chars_per_token：实测 {report['llm_economics']['chars_per_token_actual']} "
        f"vs 配置 {report['llm_economics']['chars_per_token_configured']}",
        "",
        "## ✅ 质量",
        f"- {report['quality']['status']}，warnings={report['quality']['warnings']}",
        "",
        "## ✨ 内容丰富（enrichment）",
        f"- {json.dumps(report.get('enrichment'), ensure_ascii=False)}",
        "",
        "## 🧠 内存",
        f"- {json.dumps(report.get('memory'), ensure_ascii=False)}",
        "",
        "## 🖥 server",
        f"- {json.dumps(report.get('server'), ensure_ascii=False)}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="生成一次 harness 运行的聚合优化报告")
    parser.add_argument("run_dir", help="harness 输出目录（含 03_llm_summary 等）")
    parser.add_argument("--out-md", default=None)
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args(argv)

    root = pathlib.Path(args.run_dir)
    report = build_run_report(root)
    out_md = pathlib.Path(args.out_md) if args.out_md else root / "run_report.md"
    out_json = pathlib.Path(args.out_json) if args.out_json else root / "run_report.json"
    out_md.write_text(render_markdown(report), encoding="utf-8")
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(render_markdown(report))
    print(f"\n[written] {out_md}\n[written] {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
