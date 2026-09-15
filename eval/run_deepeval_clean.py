#!/usr/bin/env python3
"""在干净输入线 n=30 上跑 DeepEval 套件(复用 deepeval_suite 的 build_case + 指标类)。

- L1 确定性(无需 key,全 30 场)：AnchorSupport(refs 接地=忠实度信号) / DecisionOwner(归属率) / KeywordPurity。
- L1 关键点召回：仅 5 场有人工金标(eval/golden/*.keypoints.json)。
- L2 千问 G-Eval(忠实度/完整度/简洁度)：设了 DASHSCOPE_API_KEY 才跑,否则跳过并提示。

干净产出是 meeting_summary.json + enrichment.json 分开的,这里拼成 build_case 期望的
meeting_result 形状(transcript+summary+enrichment)再喂。
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "eval"))

from deepeval_suite import build_case  # noqa: E402
from metrics.deterministic_metrics import (  # noqa: E402
    AnchorSupportMetric, KeywordPurityMetric, DecisionOwnerMetric,
)
from metrics.keypoint_recall_metric import KeypointRecallMetric  # noqa: E402

# 人工关键点金标 → clean mid 映射(仅这些场能跑 L1 关键点召回)
GOLDEN_MAP = {
    "20200708_L_R002S05C01": "eval/golden/R002S05C01.keypoints.json",
    "20200708_L_R002S03C01": "eval/golden/R002S03C01.keypoints.json",
    "20200706_L_R001S08C01": "eval/golden/R001S08C01_law.keypoints.json",
    "20200707_L_R001S04C01": "eval/golden/g1_school_ops.keypoints.json",
}


def _assemble(mid: str) -> Path | None:
    od = ROOT / "eval/_pc_clean" / mid
    sp = od / "meeting_summary.json"
    if not sp.exists():
        return None
    d = json.loads((od / "meeting_result.json").read_text(encoding="utf-8"))
    d["summary"] = json.loads(sp.read_text(encoding="utf-8"))
    ep = od / "enrichment.json"
    d["enrichment"] = json.loads(ep.read_text(encoding="utf-8")) if ep.exists() else {}
    out = od / "_deepeval_result.json"
    out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> int:
    mids = sorted(p.name[: -len(".golden.json")]
                  for p in (ROOT / "eval/golden_v2/out").glob("*.golden.json"))
    have_key = bool(os.environ.get("DASHSCOPE_API_KEY"))
    # 裁判选择:默认本地 Ollama(无 key、不出网);JUDGE_BACKEND=qwen 且设了 DASHSCOPE_API_KEY 才用云千问。
    # --no-l2:只跑 L1 确定性(run_all 的确定性骨架用,不碰裁判)。
    l2 = []
    backend = os.environ.get("JUDGE_BACKEND", "ollama")
    if "--no-l2" in sys.argv:
        print("--no-l2 → 仅跑 L1 确定性")
        backend = "none"
    try:
        if backend == "none":
            raise RuntimeError("L2 skipped")
        from metrics.geval_metrics import faithfulness, completeness, conciseness
        if backend == "qwen" and have_key:
            from judge.qwen_judge import QwenJudge
            judge = QwenJudge()
            print(f"L2 裁判 = 云千问({judge.get_model_name()})")
        else:
            from judge.ollama_judge import OllamaJudge
            judge = OllamaJudge()
            print(f"L2 裁判 = 本地 Ollama({judge.get_model_name()}),无 key。需 `ollama pull {judge.model}`(或 JUDGE_MODEL 指定已装模型)")
        l2 = [faithfulness(judge), completeness(judge), conciseness(judge)]
    except Exception as exc:  # noqa: BLE001 —— 裁判初始化失败不阻断 L1
        print(f"!! L2 裁判初始化失败,仅跑 L1: {type(exc).__name__}: {exc}")

    # 空金标(给无人工金标的场,让 build_case 能构造;KeypointRecall 不对它们跑)
    empty_golden = Path(tempfile.gettempdir()) / "_empty_keypoints.json"
    empty_golden.write_text(json.dumps({"meeting": "", "key_points": []}, ensure_ascii=False), encoding="utf-8")

    det = [AnchorSupportMetric(0.8), KeywordPurityMetric(0.9), DecisionOwnerMetric(0.3)]
    kp = KeypointRecallMetric(threshold=0.8)
    kp_lf = KeypointRecallMetric(threshold=0.8, low_freq_only=True)

    rows = []
    for mid in mids:
        mr = _assemble(mid)
        if mr is None:
            continue
        gpath = ROOT / GOLDEN_MAP[mid] if mid in GOLDEN_MAP else empty_golden
        tc = build_case(mr, gpath, mid)
        row = {"mid": mid, "has_golden": mid in GOLDEN_MAP}
        def _rd(x):
            return round(x, 3) if isinstance(x, (int, float)) else None
        for m in det:
            m.measure(tc); row[m.__class__.__name__] = _rd(m.score)
        if mid in GOLDEN_MAP:
            kp.measure(tc); kp_lf.measure(tc)
            row["KeypointRecall"] = _rd(kp.score)
            row["KeypointRecall_lowfreq"] = _rd(kp_lf.score)
        for m in l2:
            try:
                m.measure(tc); row[m.name] = round(float(m.score or 0), 3)
            except Exception as exc:  # noqa: BLE001
                row[m.name] = f"ERR:{type(exc).__name__}"
        rows.append(row)
        print(f"[{mid[-13:]}] " + "  ".join(f"{k}={v}" for k, v in row.items()
                                            if k not in ("mid", "has_golden")))

    # 汇总
    def avg(key):
        xs = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return sum(xs) / len(xs) if xs else None
    print("=" * 78)
    n = len(rows)
    keys = ["AnchorSupportMetric", "KeywordPurityMetric", "DecisionOwnerMetric"] + [m.name for m in l2]
    print(f"n={n}  " + "  ".join(f"{k}均值={avg(k):.3f}" for k in keys if avg(k) is not None))
    gk = [r for r in rows if r["has_golden"]]
    if gk:
        kpv = [r["KeypointRecall"] for r in gk if isinstance(r.get("KeypointRecall"), (int, float))]
        klv = [r["KeypointRecall_lowfreq"] for r in gk if isinstance(r.get("KeypointRecall_lowfreq"), (int, float))]
        kpa = sum(kpv) / len(kpv) if kpv else float("nan")
        kla = sum(klv) / len(klv) if klv else float("nan")
        print(f"关键点召回(n={len(gk)}人工金标): 全部={kpa:.3f}(n={len(kpv)})  低频={kla:.3f}(n={len(klv)})")
    out = ROOT / "eval/reports/deepeval_clean"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {out/'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
