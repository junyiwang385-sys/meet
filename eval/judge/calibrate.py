#!/usr/bin/env python3
"""裁判校准(评测线规划 L2 校准闸门)。

问题:千问裁判的忠实/完整分可信吗?——先用【人工金标】当真值校准它。
方法:对每个金标关键点,问裁判"这个点在纪要里覆盖了吗(是/否)",
     和确定性召回(anchor 命中≥半数=覆盖)比一致率。
判定:一致率 ≥ 0.8 → 裁判在"覆盖判断"上可信,其 G-Eval 完整度分可采信;
     < 0.8 → 该维度不采信(只作参考)。

用法(先设 DASHSCOPE_API_KEY):
  python eval/judge/calibrate.py --config eval/eval_config_deepeval.json --out eval/reports/deepeval
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # eval/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from summary.keypoint_recall import score as kp_score  # noqa: E402
from qwen_judge import QwenJudge                        # noqa: E402

SYS = ('给你一份会议纪要和一个"关键点"。判断这个关键点的信息是否在纪要中被覆盖(哪怕换了说法)。'
       '只输出JSON:{"covered": true} 或 {"covered": false}。')


def minutes_text(meeting_result_path: Path) -> str:
    d = json.loads(meeting_result_path.read_text(encoding="utf-8"))
    s = d.get("summary") or {}
    e = d.get("enrichment") or {}
    parts = []
    ov = s.get("overview")
    parts.append(ov.get("text") if isinstance(ov, dict) else str(ov or ""))
    for ch in s.get("chapters") or []:
        parts.append(f"{ch.get('title','')}:{ch.get('overview','')}")
    for qa in (e.get("qa") or []):
        parts.append(f"{qa.get('question','')} {qa.get('answer','')}")
    for dec in (e.get("decisions") or []):
        parts.append(dec.get("decision", "") if isinstance(dec, dict) else str(dec))
    return "\n".join(p for p in parts if p)


def main() -> None:
    ap = argparse.ArgumentParser(description="裁判校准(对人工金标)")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "deepeval")
    ap.add_argument("--judge-model", default="qwen3.8-max")
    args = ap.parse_args()

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    judge = QwenJudge(model=args.judge_model)
    agree = total = 0
    rows = []
    for case in cfg.get("cases", []):
        mt = minutes_text(Path(case["meeting_result"]))
        golden = json.loads(Path(case["golden"]).read_text(encoding="utf-8"))
        missed = set(kp_score({"t": mt}, golden)["missed_ids"])  # 确定性:不在missed即覆盖
        for kp in golden.get("key_points", []):
            kid = kp.get("id")
            det_cov = kid not in missed
            prompt = f"会议纪要:\n{mt[:6000]}\n\n关键点:{kp.get('desc','')}"
            r = judge.generate(f"{SYS}\n\n{prompt}", schema=None)
            judge_cov = '"covered": true' in r.lower() or '"covered":true' in r.lower()
            match = (det_cov == judge_cov)
            agree += int(match); total += 1
            rows.append({"meeting": case["meeting"], "kp": kid,
                         "det": det_cov, "judge": judge_cov, "match": match})
    rate = round(agree / total, 3) if total else 0.0
    verdict = "可信(≥0.8,G-Eval完整度可采信)" if rate >= 0.8 else "不采信(<0.8,仅参考)"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "calibration.json").write_text(
        json.dumps({"agreement": rate, "n": total, "verdict": verdict, "rows": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    dis = [r for r in rows if not r["match"]]
    print(f"裁判校准:一致率 {rate}  ({agree}/{total})  → {verdict}")
    if dis:
        print("分歧点:", [(r["meeting"], r["kp"], f"det={r['det']}/judge={r['judge']}") for r in dis])


if __name__ == "__main__":
    main()
