#!/usr/bin/env python3
"""A0 vs A1 严格对照(生产代码 _block_summary_messages,唯一变量=带不带上一章carryover)。

A1 = 现生产行为:每章把上一章 {title,summary} 作为 prev_context 喂入
A0 = prev_context 恒 None(单章隔离)
其余全同:同分章、同生产提示词、同 profile、temp0。

指标(章级块摘要,合并前,避免 continues 合并混淆):
  recall     关键点召回(仅 g1/g2 有金标)
  contam     串味率 = key_refs 落到本章之外 / 全部 key_refs
  avg_chars  摘要均字

用法(Ollama 在跑):
  python eval/a0_vs_a1_production.py --out eval/reports/a0_vs_a1
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "eval" / "summary"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession
from meeting_agent.stages.product_summary import (
    _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map)
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE
from meeting_agent.stages.validation import parse_content
import keypoint_recall as KR

BOARD = ROOT / "ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
MEETINGS = [  # (名, meeting_result, golden或None)
    ("g1", BOARD/"g1/harness/meeting_result.json", ROOT/"eval/golden/g1_school_ops.keypoints.json"),
    ("g2", BOARD/"g2/harness/meeting_result.json", ROOT/"eval/golden/R002S05C01.keypoints.json"),
    ("g3", BOARD/"g3/harness/meeting_result.json", None),
    ("g4", BOARD/"g4/harness/meeting_result.json", None),
    ("g5", BOARD/"g5/harness/meeting_result.json", None),
]


def chapters(mr: Path):
    d = json.loads(mr.read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    idx = {s["segment_id"]: i for i, s in enumerate(segs)}
    out = []
    for ch in (d.get("summary") or {}).get("chapters") or []:
        a, b = ch.get("start_ref"), ch.get("end_ref")
        m = segs[idx[a]:idx[b]+1] if a in idx and b in idx else []
        out.append([s for s in m if (s.get("text") or "").strip()])
    return out


def run_arm(chs, session, carry: bool, tag: str):
    summaries, refs_out, refs_tot, chars = [], 0, 0, []
    prev = None
    for i, seg in enumerate(chs):
        rm, _ = _build_compact_ref_map(seg)
        sm, _ = _build_compact_speaker_map([s.get("speaker_id", "") for s in seg])
        comp2canon = {v: k for k, v in rm.items()}
        ids = {s["segment_id"] for s in seg}
        msgs = _block_summary_messages(seg, prev if carry else None, ref_map=rm, speaker_map=sm, profile=GENERIC_PROFILE)
        r = session.request(msgs, session.out_dir/f"{tag}_{i}" if hasattr(session,'out_dir') else Path(".")/f"{tag}_{i}",
                            max_tokens=900, request_kind="a0a1")
        raw = parse_content(r.get("content","")) or {}
        summ = str(raw.get("summary","")).strip()
        summaries.append(summ); chars.append(len(summ))
        for rf in (raw.get("key_refs") or []):
            canon = comp2canon.get(str(rf), str(rf)); refs_tot += 1
            if canon not in ids: refs_out += 1
        if carry:
            prev = {"title": str(raw.get("title","")).strip(), "summary": summ}
    return {"summaries": summaries, "avg_chars": round(sum(chars)/max(1,len(chars))),
            "contam": round(refs_out/refs_tot, 3) if refs_tot else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT/"reports"/"a0_vs_a1")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, mr, golden in MEETINGS:
        if not mr.exists():
            print("跳过", name); continue
        chs = chapters(mr)
        session = OllamaSession(OllamaConfig(model="qwen3:4b", max_tokens=900), args.out/f"_{name}")
        session.out_dir = args.out/f"_{name}"
        a0 = run_arm(chs, session, carry=False, tag="A0")
        a1 = run_arm(chs, session, carry=True, tag="A1")
        g = json.loads(golden.read_text(encoding="utf-8")) if golden else None
        def rec(a):
            if not g: return None
            return KR.score({"c":[{"overview":s} for s in a["summaries"]]}, g)["recall"]
        row = {"meeting": name, "chapters": len(chs),
               "A0_recall": rec(a0), "A1_recall": rec(a1),
               "A0_contam": a0["contam"], "A1_contam": a1["contam"],
               "A0_chars": a0["avg_chars"], "A1_chars": a1["avg_chars"],
               "A0_sum": a0["summaries"], "A1_sum": a1["summaries"]}
        rows.append(row)
        print(f"[{name}] 召回 A0={row['A0_recall']} A1={row['A1_recall']} | 串味 A0={row['A0_contam']} A1={row['A1_contam']} | 字 A0={row['A0_chars']} A1={row['A1_chars']}")
        (args.out/"a0_vs_a1.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def avg(key, cond=lambda r: True):
        vs = [r[key] for r in rows if cond(r) and isinstance(r.get(key),(int,float))]
        return round(sum(vs)/len(vs),3) if vs else None
    print("\n==== 汇总 ====")
    print(f"召回(g1/g2):  A0={avg('A0_recall')}  A1={avg('A1_recall')}")
    print(f"串味(5场):    A0={avg('A0_contam')}  A1={avg('A1_contam')}")
    print(f"均字(5场):    A0={avg('A0_chars')}  A1={avg('A1_chars')}")


if __name__ == "__main__":
    main()
