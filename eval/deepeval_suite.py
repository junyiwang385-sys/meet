#!/usr/bin/env python3
"""会议纪要质量评测套件(基于 DeepEval + 千问裁判)。

融合已有工作:
  - 输入 = 板端 meeting_result.json(summary.chapters + enrichment,真实产物)
  - 金标 = eval/golden/*.keypoints.json(人工关键点)
  - 关键点召回 = 复用 eval/summary/keypoint_recall.py(包成 DeepEval 自定义 metric)
  - 忠实度/完整度 = DeepEval G-Eval,裁判千问 qwen3.8-max

四个指标(L1确定性 + L2裁判):
  关键点召回(全部) / 低频精确召回 —— 确定性,对金标,判定依据
  忠实度 / 完整度 —— G-Eval,千问裁判,质量参考

用法(先设 DASHSCOPE_API_KEY):
  set PYTHONIOENCODING=utf-8
  set DASHSCOPE_API_KEY=sk-...
  python eval/deepeval_suite.py --config eval/eval_config_deepeval.json --out eval/reports/deepeval

config: {"cases":[{"meeting":"g2","meeting_result":"...json","golden":"eval/golden/R002S05C01.keypoints.json"}]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from deepeval import evaluate                                    # noqa: E402
from deepeval.evaluate.configs import AsyncConfig, DisplayConfig  # noqa: E402
from deepeval.test_case import LLMTestCase                       # noqa: E402

from judge.qwen_judge import QwenJudge                           # noqa: E402
from metrics.keypoint_recall_metric import KeypointRecallMetric  # noqa: E402
from metrics.geval_metrics import faithfulness, completeness     # noqa: E402


def build_case(meeting_result_path: Path, golden_path: Path, meeting: str):
    """从板端 meeting_result.json 造 LLMTestCase：input=原文, actual_output=纪要文本,
    additional_metadata 带 {golden, minutes} 供确定性召回 metric 使用。"""
    d = json.loads(meeting_result_path.read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    summary = d.get("summary") or {}
    enrich = d.get("enrichment") or {}

    # 原文(判忠实/完整用):必须喂全文,否则纪要覆盖全会而原文被截→裁判误判"编造"。
    # qwen-max 上下文大,30min 会 ~8k 字直接喂;超长会再议(截断会伤忠实度效度)。
    transcript = "".join((s.get("text") or "").strip() for s in segs)[:15000]

    # 纪要可读文本(给裁判看的"实际产出")
    parts: list[str] = []
    if summary.get("overview"):
        ov = summary["overview"]
        parts.append("【全文纪要】" + (ov.get("text") if isinstance(ov, dict) else str(ov)))
    for ch in summary.get("chapters") or []:
        parts.append(f"【章】{ch.get('title','')}：{ch.get('overview','')}")
    if enrich.get("keywords"):
        parts.append("【关键词】" + "、".join(map(str, enrich["keywords"])))
    for qa in (enrich.get("qa") or [])[:20]:
        parts.append(f"【问答】{qa.get('question','')} — {qa.get('answer','')}")
    for dec in (enrich.get("decisions") or [])[:20]:
        parts.append(f"【决策】{dec.get('decision','') if isinstance(dec, dict) else dec}")
    actual_output = "\n".join(parts)

    # minutes 结构化 dict(给确定性召回搜锚词——含全层,章节+enrichment)
    minutes = {"summary": summary, "enrichment": enrich}
    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    return LLMTestCase(
        input=transcript,
        actual_output=actual_output,
        additional_metadata={"golden": golden, "minutes": minutes, "meeting": meeting},
    )


def _metric_row(metrics_data) -> dict:
    out = {}
    for m in metrics_data:
        out[m.name] = {"score": m.score, "success": m.success,
                       "reason": (m.reason or "")[:160]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="会议纪要质量评测(DeepEval+千问)")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "deepeval")
    ap.add_argument("--judge-model", default="qwen3.8-max")
    args = ap.parse_args()

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    judge = QwenJudge(model=args.judge_model)
    metrics = [
        KeypointRecallMetric(threshold=0.8),
        KeypointRecallMetric(threshold=0.8, low_freq_only=True),
        faithfulness(judge),
        completeness(judge),
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cfg.get("cases", []):
        tc = build_case(Path(case["meeting_result"]), Path(case["golden"]), case["meeting"])
        result = evaluate(
            [tc], metrics,
            async_config=AsyncConfig(run_async=False),           # 确定性 metric 用同步
            display_config=DisplayConfig(print_results=False, show_indicator=False),
        )
        md = _metric_row(result.test_results[0].metrics_data)
        md["meeting"] = case["meeting"]
        rows.append(md)
        print(f"[{case['meeting']}] " + "  ".join(
            f"{k}={v['score']}" for k, v in md.items() if isinstance(v, dict)))

    # 报告
    (args.out / "deepeval_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    # 列名从实际结果动态取(指标名带 DeepEval 后缀如 "忠实度 [GEval]",不硬编码防对不上)
    names: list[str] = []
    for r in rows:
        for k, v in r.items():
            if isinstance(v, dict) and k not in names:
                names.append(k)
    L = ["# 会议纪要质量评测(DeepEval + 千问 qwen3.8-max)", "",
         f"- 会议数：{len(rows)}  裁判：{args.judge_model}",
         "- L1 确定性(对金标)：关键点召回 / 低频精确召回；L2 裁判(千问)：忠实度 / 完整度", "",
         "| 会议 | " + " | ".join(names) + " |",
         "|---|" + "---|" * len(names)]
    for r in rows:
        cells = [str((r.get(n) or {}).get("score", "-")) for n in names]
        L.append(f"| {r['meeting']} | " + " | ".join(cells) + " |")
    L += ["", "## 诚实边界",
          "- L1(召回)确定性、可复现,是判定依据;L2(忠实/完整)千问裁判,质量参考。",
          "- 输入为板端 003 产物(旧版 enrichment);改造后需重跑板端再评。",
          "- 裁判为云端千问,仅评测用,不影响端侧离线部署。"]
    (args.out / "RESULTS_deepeval.md").write_text("\n".join(L), encoding="utf-8")
    print(f"\n→ {args.out / 'RESULTS_deepeval.md'}")


if __name__ == "__main__":
    main()
