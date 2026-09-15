#!/usr/bin/env python3
"""决策符合度评测(全 LLM 判)—— over_decision / missed_decision / critical / 忠实度。

方法学(见 docs 对标 + 评测框架总览 §指标契约 组3):
  金标 decision/proposal 标签作**权威锚**,裁判只做候选↔金标语义匹配,不重判什么算决定。
  忠实度=(supported+0.5·partial)/claims;over=proposal被当决定;missed=decision没捕获;critical=编造。
  **校准后趋势,不设硬门禁**(裁判有波动)。

裁判两条路(都不需要云 key):
  - 默认(自动、一键):本地 Ollama 裁判内联判 → 直接出 RESULTS_conformance。
  - 权威(--emit DIR):把每场提示词导出到 DIR,由 opus 子agent 判后回填 DIR/<mid>.result.json,
    再 `--collect DIR` 聚合。三方分离(候选4B/金标fable5/裁判opus)最干净。

用法:
  python eval/conformance/run_conformance.py                 # 本地 Ollama 判全30场
  python eval/conformance/run_conformance.py --emit  E:/j    # 导出提示词给 opus
  python eval/conformance/run_conformance.py --collect E:/j  # 回填后聚合
"""
from __future__ import annotations
import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "eval" / "conformance"))
sys.path.insert(0, str(ROOT / "eval"))
from judge_prompt import build_judge_prompt, candidate_text_from, load_clean, timeline_text  # noqa: E402

OUT = ROOT / "eval/reports/conformance"


def _mids() -> list[str]:
    return sorted(p.name[: -len(".golden.json")]
                  for p in (ROOT / "eval/golden_v2/out").glob("*.golden.json")
                  if (ROOT / "eval/_pc_clean" / p.name[: -len(".golden.json")] / "meeting_summary.json").exists())


def _golden(mid: str) -> dict:
    return json.loads((ROOT / f"eval/golden_v2/out/{mid}.golden.json").read_text(encoding="utf-8"))


def _prompt_for(mid: str) -> str:
    mr = load_clean(mid)
    return build_judge_prompt(candidate_text_from(mr), _golden(mid), timeline_text(mr))


def _parse(text: str) -> dict:
    """容错解析裁判 JSON:去 ```fence、截第一个平衡花括号。"""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except Exception:
        s = t.find("{")
        if s < 0:
            raise
        depth = 0
        for i in range(s, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(t[s : i + 1])
        raise


def _row(mid: str, r: dict) -> dict:
    claims = r.get("claims") or []
    over = r.get("over_decisions") or []
    missed = r.get("missed_decisions") or []
    return {
        "mid": mid,
        "faithfulness": r.get("faithfulness"),
        "claims": len(claims),
        "over_decision": len(over),
        "missed_decision": len(missed),
        "critical": r.get("critical_count", 0),
        "verdict": r.get("verdict"),
    }


def _aggregate(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(rows)
    fvals = [float(r["faithfulness"]) for r in rows if isinstance(r.get("faithfulness"), (int, float))]
    fmean = sum(fvals) / len(fvals) if fvals else float("nan")
    ov = sum(r["over_decision"] for r in rows)
    mi = sum(r["missed_decision"] for r in rows)
    cr = sum(r["critical"] for r in rows)
    L = ["# 决策符合度(全 LLM 判)· 结果", "",
         f"> 裁判判定,金标标签权威锚;校准后趋势,不设硬门禁。n={n}。", "",
         f"- **忠实度均值 = {fmean:.3f}**(n={len(fvals)})",
         f"- **over_decision 总 {ov} · 均 {ov/n:.2f}/场**(提议被升格为决定/待办)",
         f"- **missed_decision 总 {mi} · 均 {mi/n:.2f}/场**(真决定未捕获,判定波动大,仅趋势)",
         f"- **critical 总 {cr} · 均 {cr/n:.2f}/场**(编造)", "",
         "| 场 | 忠实度 | claims | over | missed | critical | verdict |",
         "|---|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        L.append(f"| {r['mid'][-13:]} | {r['faithfulness']} | {r['claims']} | "
                 f"{r['over_decision']} | {r['missed_decision']} | {r['critical']} | {r.get('verdict','')} |")
    (OUT / "RESULTS_conformance.md").write_text("\n".join(L), encoding="utf-8")
    print(f"忠实度={fmean:.3f}  over={ov}({ov/n:.2f}/场)  missed={mi}({mi/n:.2f}/场)  critical={cr}")
    print(f"→ {OUT/'RESULTS_conformance.md'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", metavar="DIR", help="导出提示词给 opus 子agent 判(不内联跑裁判)")
    ap.add_argument("--collect", metavar="DIR", help="回填 opus 判定 <mid>.result.json 后聚合")
    args = ap.parse_args()
    mids = _mids()
    print(f"n={len(mids)} 场")

    if args.emit:
        d = pathlib.Path(args.emit); d.mkdir(parents=True, exist_ok=True)
        for mid in mids:
            (d / f"{mid}.prompt.txt").write_text(_prompt_for(mid), encoding="utf-8")
        (d / "_manifest.json").write_text(json.dumps(mids, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已导出 {len(mids)} 份提示词 → {d}\n交给 opus 子agent 判,结果回填 {d}/<mid>.result.json,再 --collect {d}")
        return 0

    if args.collect:
        d = pathlib.Path(args.collect)
        rows = []
        for mid in mids:
            p = d / f"{mid}.result.json"
            if not p.exists():
                print(f"  缺 {mid}.result.json,跳过"); continue
            rows.append(_row(mid, json.loads(p.read_text(encoding="utf-8"))))
        _aggregate(rows)
        return 0

    # 默认:本地 Ollama 内联判
    from judge.ollama_judge import OllamaJudge
    judge = OllamaJudge()
    print(f"裁判 = {judge.get_model_name()}(本地,无 key)")
    rows = []
    for i, mid in enumerate(mids, 1):
        try:
            text = judge.generate(_prompt_for(mid))
            rows.append(_row(mid, _parse(text)))
            print(f"[{i}/{len(mids)}] {mid[-13:]} 忠实度={rows[-1]['faithfulness']} over={rows[-1]['over_decision']}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(mids)}] {mid[-13:]} 裁判失败: {type(exc).__name__}: {exc}")
    if rows:
        _aggregate(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
