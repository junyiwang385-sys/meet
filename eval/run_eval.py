"""多场会评测汇总入口（简历级评测框架）。

对一组会议，各阶段跑指标、汇总均值+方差，生成一份可复现的 RESULTS.md。
目的：把"单点实验"升级为"多场、对金标准、有基线、可复现"的可信度量。

阶段与指标：
  - 分章  Pk / WindowDiff（对人工金标准，越低越好）——复用 topic_segmentation/pk_windowdiff.py
  - 摘要  关键点召回（对人工关键点金标准，越高越好）——summary/keypoint_recall.py
  - 纠错  纠回率 / 精确率（对专名 ground truth）——可选
  - 转写  CER（对 TextGrid，需时间对齐）——占位，未实现

用法：
  python run_eval.py --config eval/eval_config.json

config 指定每场会的：转写/纪要产物路径 + 各金标准路径。缺哪项跳过哪项。
⚠️ 金标准（分章边界、摘要关键点）需人工标注——是本框架的主要工作量，也是可信度来源。

诚实边界（务必写进 RESULTS.md）：PC 等价替代非板端复现；场次有限非大规模 benchmark；
关键未验：1-2h 长会 + 板端端到端。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from summary.keypoint_recall import score as kp_score  # noqa: E402


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values)
    s = statistics.pstdev(values) if len(values) > 1 else 0.0
    return round(m, 3), round(s, 3)


def run(config: dict) -> dict:
    rows = []
    for case in config.get("cases", []):
        meeting = case["meeting"]
        row: dict = {"meeting": meeting}
        # 摘要关键点召回
        if case.get("minutes") and case.get("keypoints_golden"):
            try:
                minutes = json.load(open(case["minutes"], encoding="utf-8"))
                golden = json.load(open(case["keypoints_golden"], encoding="utf-8"))
                r = kp_score(minutes, golden)
                row["kp_recall"] = r["recall"]
                row["kp_missed"] = r["missed_ids"]
            except Exception as exc:  # noqa: BLE001
                row["kp_recall_error"] = str(exc)
        # 分章 Pk/WindowDiff：调用现成脚本较重，这里留接口，实测时用
        # topic_segmentation/pk_windowdiff.py 单跑后把结果填进 case["pk"]/["windowdiff"]
        for k in ("pk", "windowdiff", "correction_recall", "correction_precision", "cer"):
            if k in case:
                row[k] = case[k]
        # 结合结构化日志：读 run_report.json，把过程/系统指标 + 自动红旗并入评测。
        # 让"系统可观测(run_report)"与"结果质量(金标准)"合成一份完整评测。
        if case.get("run_report"):
            try:
                rr = json.load(open(case["run_report"], encoding="utf-8"))
                row["flags"] = rr.get("flags", [])
                seg = rr.get("segmentation", {})
                row["block_count"] = seg.get("block_count")
                row["chapter_count"] = seg.get("chapter_count")
                blk = rr.get("blocks", {})
                row["block_summary_avg_chars"] = (blk.get("summary_chars") or {}).get("avg")
                row["retry_count"] = len(blk.get("retried_block_ids") or [])
                econ = rr.get("llm_economics", {})
                row["prompt_tokens"] = econ.get("total_prompt_tokens")
                tm = rr.get("timing", {})
                row["total_elapsed_s"] = tm.get("total_seconds")
            except Exception as exc:  # noqa: BLE001
                row["run_report_error"] = str(exc)
        rows.append(row)
    # 汇总
    agg = {}
    for metric in ("kp_recall", "pk", "windowdiff", "correction_recall", "correction_precision", "cer"):
        vals = [r[metric] for r in rows if isinstance(r.get(metric), (int, float))]
        if vals:
            m, s = _mean_std(vals)
            agg[metric] = {"mean": m, "std": s, "n": len(vals)}
    return {"cases": rows, "aggregate": agg, "n_meetings": len(rows)}


def render_md(result: dict, config: dict) -> str:
    L = ["# 评测结果（多场会）", ""]
    L.append(f"会议数: {result['n_meetings']}  |  评测框架: eval/run_eval.py（可复现）")
    L.append("")
    L.append("## 汇总（均值 ± 标准差）")
    L.append("")
    L.append("| 指标 | 均值 | 标准差 | 场次 | 说明 |")
    L.append("|---|---|---|---|---|")
    desc = {"kp_recall": "摘要关键点召回(↑)", "pk": "分章Pk(↓)", "windowdiff": "分章WindowDiff(↓)",
            "correction_recall": "专名纠回率(↑)", "correction_precision": "专名精确率(↑)", "cer": "转写字错率(↓)"}
    for k, v in result["aggregate"].items():
        L.append(f"| {desc.get(k, k)} | {v['mean']} | ±{v['std']} | {v['n']} | |")
    L.append("")
    L.append("## 逐场·结果质量（对金标准）")
    L.append("")
    L.append("| 会议 | 关键点召回 | Pk | WindowDiff | 纠回率 | 精确率 | CER |")
    L.append("|---|---|---|---|---|---|---|")
    for r in result["cases"]:
        L.append(f"| {r['meeting']} | {r.get('kp_recall','-')} | {r.get('pk','-')} | "
                 f"{r.get('windowdiff','-')} | {r.get('correction_recall','-')} | "
                 f"{r.get('correction_precision','-')} | {r.get('cer','-')} |")
    L.append("")
    L.append("## 逐场·过程/系统指标（来自结构化日志 run_report）")
    L.append("")
    L.append("| 会议 | 块数→章数 | 块摘要均字 | 重试 | prompt tokens | 总耗时(s) |")
    L.append("|---|---|---|---|---|---|")
    for r in result["cases"]:
        bc = f"{r.get('block_count','-')}→{r.get('chapter_count','-')}"
        L.append(f"| {r['meeting']} | {bc} | {r.get('block_summary_avg_chars','-')} | "
                 f"{r.get('retry_count','-')} | {r.get('prompt_tokens','-')} | {r.get('total_elapsed_s','-')} |")
    L.append("")
    L.append("## 自动优化红旗（来自 run_report）")
    L.append("")
    for r in result["cases"]:
        flags = r.get("flags") or []
        if flags:
            L.append(f"**{r['meeting']}**：")
            for f in flags:
                L.append(f"- 🚩 {f}")
            L.append("")
    L.append("## 诚实边界")
    L.append("- 全部 PC 等价替代（Ollama GGUF Q4 / transformers Qwen3-ASR / modelscope diar），非板端 RKLLM/RKNN/板端 3D-Speaker 复现。")
    L.append("- 场次有限，非大规模 benchmark；金标准为人工标注。")
    L.append("- **关键未验：1-2h 长会（项目卖点）+ 板端端到端。**")
    L.append("- 摘要若用 LLM-judge，须注明用了哪个（更大/云端）模型，仅评测用、不属端侧部署。")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="多场会评测汇总")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default="eval/reports/RESULTS.md")
    args = ap.parse_args()
    config = json.load(open(args.config, encoding="utf-8"))
    result = run(config)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(render_md(result, config), encoding="utf-8")
    json.dump(result, open(args.out.replace(".md", ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"SAVED {args.out}")
    print(json.dumps(result["aggregate"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
