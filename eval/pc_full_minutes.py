"""PC 全量真实摘要流水线：真实板端转写 + Ollama qwen3:4b 走真 stage
(product_summary 分块 map-reduce + enrichment)，出一份可读会议纪要看效果。

板端已无访问后，这是 PC 端端到端看产品输出的路子——OllamaSession 与 RkllmServerSession
鸭子对齐，run_product_summary_stage 无需改动即可换后端(session 注入)。

用法: python eval/pc_full_minutes.py [board_meeting_result.json] [out_dir]
默认输入 = g1 板端真实转写(336 段/30min)。
前提: ollama serve 在跑 + qwen3:4b 已 pull(OLLAMA_MODELS=E:/ollama-models)。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "src"))

from meeting_agent.llm.llm import LlmConfig  # noqa: E402
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession  # noqa: E402
from meeting_agent.stages.product_summary import (  # noqa: E402
    ProductSummaryConfig,
    run_product_summary_stage,
)
from meeting_agent.stages.enrichment import run_enrichment_stage  # noqa: E402
from meeting_agent.stages.transcript import render_timeline  # noqa: E402
from meeting_agent.stages.display import build_frontend_result, render_meeting_display  # noqa: E402


def _pc_llm_config() -> LlmConfig:
    # 注入 session 后 model_dir/server/host/port 不用；仅 ctx/max_tokens 参与预算。
    dummy = pathlib.Path(".")
    return LlmConfig(
        board_scripts_dir=dummy, model_dir=dummy, server=dummy,
        host="127.0.0.1", port=18245,
        ctx=16384, predict=3072, max_tokens=3072,
        temperature=0.0, server_temp=0.0, server_top_k=1,
        server_top_p=1.0, server_repeat_penalty=1.05,
        ready_timeout=300, request_timeout=1200,
    )


def main() -> int:
    default_mr = ROOT / "ops/board-results/2026-09-02_003_enrichment-wire-board-verify/g1/harness/meeting_result.json"
    mr = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else default_mr
    out_dir = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else (ROOT / "eval/_pc_full_minutes/g1")
    out_dir.mkdir(parents=True, exist_ok=True)

    d = json.loads(mr.read_text(encoding="utf-8"))
    meeting = d.get("meeting") or {"meeting_id": "pc-run"}
    segments = (d.get("transcript") or {}).get("segments") or []
    if not segments:
        print("!! 输入无 transcript.segments", flush=True)
        return 2
    speaker_ids = sorted({s["speaker_id"] for s in segments})
    timeline = render_timeline(segments)
    print(f"输入: {mr}\n  段数={len(segments)}  发言人={speaker_ids}", flush=True)

    session = OllamaSession(OllamaConfig(model="qwen3:4b", max_tokens=3072), out_dir)
    t0 = time.time()
    llm_run = run_product_summary_stage(
        config=ProductSummaryConfig(
            llm=_pc_llm_config(), safety_tokens=512,
            chars_per_token=1.55, fixed_overhead_tokens=128, resume=False,
        ),
        segments=segments, speaker_ids=speaker_ids, timeline=timeline,
        out_dir=out_dir, sampler=None, run_log=None, session=session,
    )
    summary = llm_run["summary"]
    print(f"[摘要] 用时 {time.time()-t0:.0f}s  策略={llm_run.get('policy')}  "
          f"请求={llm_run.get('request_count')}  章节={len(summary.get('chapters') or [])}  "
          f"发言人纪要={len(summary.get('speakers') or [])}  待办={len(summary.get('action_items') or [])}", flush=True)

    enrichment: dict = {}
    try:
        chapter_summaries = [str(c.get("overview") or "") for c in (summary.get("chapters") or []) if c.get("overview")]
        enrich = run_enrichment_stage(
            session=session, segments=segments, out_dir=out_dir,
            chapter_summaries=chapter_summaries, run_log=None, max_predict=3072,
        )
        enrichment = enrich["enrichment"]
        print(f"[enrichment] 关键词={len(enrichment.get('keywords') or [])} "
              f"问答={len(enrichment.get('qa') or [])} 金句={len(enrichment.get('quotes') or [])} "
              f"决策={len(enrichment.get('decisions') or [])}", flush=True)
    except Exception as exc:  # noqa: BLE001 —— enrichment 增强性质，失败不阻断
        print(f"[enrichment] 跳过/失败: {type(exc).__name__}: {exc}", flush=True)

    frontend = build_frontend_result(meeting, segments, summary, context_policy=llm_run.get("policy"))
    display = render_meeting_display(frontend)
    (out_dir / "meeting_display.txt").write_text(display, encoding="utf-8")
    (out_dir / "meeting_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if enrichment:
        (out_dir / "enrichment.json").write_text(json.dumps(enrichment, ensure_ascii=False, indent=2), encoding="utf-8")
    session.close()

    print("\n================= 会议纪要(可读) =================\n", flush=True)
    print(display, flush=True)
    print(f"\n(已存 {out_dir}/meeting_display.txt)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
