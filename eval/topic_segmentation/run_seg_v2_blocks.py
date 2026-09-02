#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在同一场会上跑确定性 A 层 seg.v2（segment_blocks），
输出块边界，并对金标准算「边界召回」+ Pk/WindowDiff。

注意：A 层刻意偏向过切（高召回、不漏切），最终章节由后续 B/C 层合并得到。
所以本脚本回答的是：**确定性层是否把金标准的每条边界都切出来了**
（若召回≈1，则合并层只需做 yes/no 归并，永远不必去“恢复漏切”）。

用法（在 meet 根目录）：
  PYTHONPATH=src PYTHONIOENCODING=utf-8 python eval/topic_segmentation/run_seg_v2_blocks.py \
      --segments "E:/task-2a83a3a8a98a/harness/03_llm_summary/canonical_segments.json" \
      --golden   eval/topic_segmentation/golden_mtg_9c6133819814365e.json
"""
import argparse
import json
import os
import sys

from meeting_agent.llm.chunking import BudgetPolicy
from meeting_agent.stages.topic_segmentation import segment_blocks, SegmentationConfig

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pk_windowdiff import (  # noqa: E402
    labels_from_golden, num_segments, boundary_k, pk, window_diff,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", required=True)
    ap.add_argument("--golden", default=os.path.join(HERE, "golden_mtg_9c6133819814365e.json"))
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--output-tokens", type=int, default=1400)
    ap.add_argument("--chars-per-token", type=float, default=1.689)
    args = ap.parse_args()

    with open(args.segments, encoding="utf-8") as f:
        raw = json.load(f)
    segs = raw["segments"] if isinstance(raw, dict) and "segments" in raw else raw
    for i, s in enumerate(segs):
        s.setdefault("index", i)

    policy = BudgetPolicy(ctx=args.ctx, output_tokens=args.output_tokens,
                          chars_per_token=args.chars_per_token)
    result = segment_blocks(segs, policy, SegmentationConfig())
    blocks = result["blocks"]

    # 每块首段 index = 一条 A 层边界。block 结构：{segment_ids:[...], start_ms,...}
    id_to_index = {str(s.get("segment_id")): s.get("index") for s in segs}
    ms_to_index = {int(s.get("start_ms")): s.get("index") for s in segs if s.get("start_ms") is not None}

    block_starts = []
    for b in blocks:
        sids = b.get("segment_ids") or []
        if sids and str(sids[0]) in id_to_index:
            block_starts.append(id_to_index[str(sids[0])])
        elif b.get("start_ms") is not None and int(b["start_ms"]) in ms_to_index:
            block_starts.append(ms_to_index[int(b["start_ms"])])
    block_starts = sorted(x for x in block_starts if x is not None)

    with open(args.golden, encoding="utf-8") as f:
        golden = json.load(f)
    gold_starts = sorted(c["start_index"] for c in golden["chapters"])
    # 内部边界 = 去掉每侧首个（起点不算“切”）
    gold_internal = [s for s in gold_starts if s != gold_starts[0]]
    a_internal = [s for s in block_starts if s != (block_starts[0] if block_starts else None)]

    # 边界召回：金标准每条内部边界，是否被某个 A 层块起点“命中”（±1 段容差）
    hit = 0
    tol = 1
    for g in gold_internal:
        if any(abs(g - a) <= tol for a in a_internal):
            hit += 1
    recall = hit / len(gold_internal) if gold_internal else 1.0

    print("=" * 60)
    print(f"A 层 seg.v2 产出块数 = {len(blocks)}（金标准 {len(golden['chapters'])} 章）")
    print(f"边界原因计数 = {result.get('boundary_reason_counts')}")
    print(f"A 层块起点(index) = {block_starts}")
    print(f"金标准章节起点(index) = {gold_starts}")
    print("-" * 60)
    print(f"金标准内部边界召回(±{tol}段容差) = {hit}/{len(gold_internal)} = {recall:.2f}")
    print("  → 召回高=确定性层没漏切，合并层只需做归并（不必恢复漏掉的边界）")

    # 顺带给个 Pk/WindowDiff（A 层 vs 金标准）：因 A 层过切，这里预期偏高，仅作参照
    segments_min = [{"index": s.get("index"), "segment_id": s.get("segment_id"),
                     "start_ms": s.get("start_ms"), "end_ms": s.get("end_ms")} for s in segs]
    gold_labels = labels_from_golden(segments_min, golden)
    # A 层标签：按块起点分段
    a_labels = []
    cur = -1
    starts_set = set(block_starts)
    for s in segments_min:
        if s["index"] in starts_set:
            cur += 1
        a_labels.append(f"a{max(cur,0)}")
    keep = [i for i, g in enumerate(gold_labels) if g is not None]
    ref = [gold_labels[i] for i in keep]
    hyp = [a_labels[i] for i in keep]
    k = boundary_k(ref)
    print("-" * 60)
    print(f"[A层 vs golden]（过切，仅参照） Pk = {pk(ref, hyp, k):.3f}  "
          f"WindowDiff = {window_diff(ref, hyp, k):.3f}  (N={len(ref)}, k={k}, A层段数={num_segments(hyp)})")


if __name__ == "__main__":
    main()
