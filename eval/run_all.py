#!/usr/bin/env python3
"""评测主入口(框架化)—— 一键跑摘要主线正式指标 → reports/RESULTS_main。

聚合三块(干净输入线 n=30):
  1. 摘要维度(确定性)     score_dimensions.py --clean      → core/决策/待办/金句
  2. L1 确定性(DeepEval)  run_deepeval_clean.py --no-l2    → 锚点支持/关键词纯净/owner归属/关键点召回
  3. 决策符合度(裁判,可选) conformance/run_conformance.py   → over/missed/critical/忠实度(存在结果才纳入)

默认只跑 1+2(确定性骨架,快、无 key);决策符合度需先单独跑 run_conformance(裁判),
本入口自动纳入其 reports/conformance/results.json。转写/分章线有各自入口,不并入。

用法:python eval/run_all.py
"""
from __future__ import annotations
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
PY = sys.executable
REP = ROOT / "eval/reports"


def _run(desc: str, args: list[str]) -> None:
    print(f"\n=== {desc} ===")
    subprocess.run([PY, *args], cwd=str(ROOT), check=False)


def _load(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _mean(rows, key):
    xs = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return sum(xs) / len(xs) if xs else None


def main() -> int:
    # 1+2:确定性骨架(快、无 key)
    _run("摘要维度(确定性)", ["eval/golden_v2/score_dimensions.py", "--clean"])
    _run("L1 确定性(DeepEval)", ["eval/run_deepeval_clean.py", "--no-l2"])

    dim = _load(REP / "dimensions/results_clean.json")
    de = _load(REP / "deepeval_clean/results.json")
    conf = _load(REP / "conformance/results.json")  # 判定层,可选

    main_report: dict = {"line": "clean n=30", "sections": {}}
    lines = ["# 评测主报告 RESULTS_main(干净输入线 n=30)", "",
             "> `run_all.py` 自动生成。确定性骨架(维度+L1)+ 可选决策符合度(裁判)。", ""]

    # 摘要维度
    if dim:
        a = dim["aggregate"]; main_report["sections"]["dimensions"] = a
        lines += ["## 摘要维度(确定性,银标)",
                  f"- core 召回 **{a['core_recall']}** · 决策覆盖 **{a['dec_cover']}**/产出 {a['dec_out']}"
                  f" · 待办覆盖 **{a['act_cover']}**/产出 {a['act_out']} · 金句逐字 **{a['quote_verbatim']}**", ""]

    # L1 确定性
    if de:
        anc = _mean(de, "AnchorSupportMetric"); kw = _mean(de, "KeywordPurityMetric"); ow = _mean(de, "DecisionOwnerMetric")
        gk = [r for r in de if r.get("has_golden")]
        kp = _mean(gk, "KeypointRecall") if gk else None
        main_report["sections"]["l1"] = {"anchor": anc, "keyword_purity": kw, "owner": ow, "keypoint_recall": kp}
        _f = lambda x: round(x, 3) if isinstance(x, (int, float)) else x
        lines += ["## L1 确定性(DeepEval,门禁类)",
                  f"- 锚点支持 **{_f(anc)}**(门禁应=1.0) · 关键词纯净 **{_f(kw)}** · owner归属 **{_f(ow)}**(趋势)"
                  + (f" · 关键点召回 **{_f(kp)}**(人工{len(gk)}场,仅校准)" if kp is not None else ""), ""]

    # 决策符合度(判定层,可选)
    if conf:
        n = len(conf)
        fmean = _mean(conf, "faithfulness")
        ov = sum(r.get("over_decision", 0) for r in conf); mi = sum(r.get("missed_decision", 0) for r in conf)
        cr = sum(r.get("critical", 0) for r in conf)
        main_report["sections"]["conformance"] = {
            "n": n, "faithfulness": fmean, "over_per": ov / n, "missed_per": mi / n, "critical_per": cr / n}
        lines += ["## 决策符合度(裁判,校准后趋势,不设硬门禁)",
                  f"- 忠实度 **{round(fmean,3) if fmean else 'n/a'}** · over_decision 均 {ov/n:.2f}/场"
                  f" · missed 均 {mi/n:.2f}/场 · critical 均 {cr/n:.2f}/场", ""]
    else:
        lines += ["## 决策符合度(裁判)", "- ⏸ 未跑:`python eval/conformance/run_conformance.py`(本地Ollama)"
                  " 或 `--emit` 走 opus 后 `--collect`;跑完自动纳入本报告。", ""]

    lines += ["---", "> 转写线 `eval/transcription/`、分章线 `eval/topic_segmentation/` 有各自入口,不并入此主报告。"]
    (REP / "RESULTS_main.md").write_text("\n".join(lines), encoding="utf-8")
    (REP / "RESULTS_main.json").write_text(json.dumps(main_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + "=" * 60)
    print("\n".join(lines[3:]))
    print(f"\n→ {REP/'RESULTS_main.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
