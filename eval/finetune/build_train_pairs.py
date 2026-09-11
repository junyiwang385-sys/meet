# -*- coding: utf-8 -*-
"""Phase1 微调训练对构造:train_S 会议 → 生产同款 A0 分块 + 块 prompt(carryover=None,A0隔离)。
每块附确定性 continues_previous(_continues_from_boundary,供最终组对时覆盖教师猜测)。
本脚本只产【输入侧】(prompt+块文本+cont_det);教师目标随后由 agent 生成。
默认选 8 场 train_S(跨列表均匀 + 含 S01),合并写 _data/train8.prompts.jsonl。"""
from __future__ import annotations
import sys, io, json, glob, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT/"src")); sys.path.insert(0, str(ROOT/"eval"/"golden_v2"))
from build_timeline import parse_textgrid
from meeting_agent.stages.product_summary import (
    _build_compact_ref_map, _build_compact_speaker_map, _block_summary_messages,
    _continues_from_boundary, BudgetPolicy)
from meeting_agent.stages.topic_segmentation import segment_blocks, SegmentationConfig
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE

def pick8():
    tgs = sorted(pathlib.Path(p).stem for p in glob.glob(r"E:/train_S/TextGrid/*.TextGrid"))
    idx = sorted(set([0] + [int(i*(len(tgs)-1)/7) for i in range(8)]))[:8]
    return [tgs[i] for i in idx]

def blocks_for(mid, budget):
    segs = [s for s in parse_textgrid(rf"E:/train_S/TextGrid/{mid}.TextGrid") if (s.get("text") or "").strip()]
    _, cref = _build_compact_ref_map(segs)
    _, cspk = _build_compact_speaker_map([s["speaker_id"] for s in segs])
    seg_by_id = {s["segment_id"]: s for s in segs}
    blocks = segment_blocks(segs, budget, SegmentationConfig())["blocks"]
    out = []
    for bi, block in enumerate(blocks):
        bsegs = [seg_by_id[sid] for sid in block["segment_ids"]]
        msgs = _block_summary_messages(bsegs, None, ref_map=cref, speaker_map=cspk, profile=GENERIC_PROFILE, key_data=None)
        out.append({"meeting": mid, "block_id": bi, "n_segs": len(bsegs),
                    "block_chars": sum(len(s.get("text") or "") for s in bsegs),
                    "cont_det": _continues_from_boundary(block), "messages": msgs})
    return out

def main():
    mids = sys.argv[1:] or pick8()
    budget = BudgetPolicy(ctx=16384, output_tokens=3072, safety_tokens=512,
                          chars_per_token=1.55, fixed_overhead_tokens=128, overlap_segments=0)
    out = ROOT/"eval/finetune/_data/train8.prompts.jsonl"; out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(out, "w", encoding="utf-8") as f:
        for mid in mids:
            recs = blocks_for(mid, budget)
            for r in recs: f.write(json.dumps(r, ensure_ascii=False)+"\n")
            total += len(recs)
            print(f"{mid}: {len(recs)} 块 (cont_det: {sum(r['cont_det'] for r in recs)} 续块)")
    print(f"\n共 {len(mids)} 场 / {total} 块 → {out}")

if __name__ == "__main__":
    main()
