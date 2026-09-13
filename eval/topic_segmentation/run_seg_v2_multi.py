#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分章 A 层(seg.v2 segment_blocks)多场泛化评测(3-5 场)。

回答：确定性 A 层分章方法在多场会议上是否稳定(边界召回)，把此前单场结论扩到多场。

参考(reference)：golden_v2 的 fine_chapters(细章)——⚠️ 是 fable5 生成 + opus5 核验的
**银标**(非人工 gold)，且其 seg-ref 基于金标 TextGrid 分段、与板端 ASR 分段不同源，
故**按时间(start_s/end_s)对齐**到板端转写段，而非按 seg-id。
预测(hyp)：生产 segment_blocks(确定性 VAD gap/换人/词汇内聚谷)。

指标：
  - 边界召回(±1 段容差)：A 层是否把银标每条内部边界都切出来(A 层刻意过切→应偏高)；
  - Pk / WindowDiff：A 层过切会偏高，仅作参照(合并层由 B/C 处理)；
  - 块数 vs 银标章数：过切/欠切倍率。

用法(meet 根目录)：PYTHONPATH=src PYTHONIOENCODING=utf-8 python eval/topic_segmentation/run_seg_v2_multi.py
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "src"))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from meeting_agent.llm.chunking import BudgetPolicy  # noqa: E402
from meeting_agent.stages.topic_segmentation import segment_blocks, SegmentationConfig  # noqa: E402
from pk_windowdiff import (  # noqa: E402
    labels_from_time_chapters, boundary_k, pk, window_diff,
)

BR = ROOT / "ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
# tag -> train_L meeting id(既有板端转写又有 golden_v2 金标的 4 场)
CASES = [
    ("g1", "20200707_L_R001S04C01"),
    ("g2", "20200708_L_R002S05C01"),
    ("g3", "20200707_L_R001S03C01"),
    ("g5", "20200709_L_R002S04C01"),
]


def load_board_segments(tag):
    d = json.loads((BR / tag / "harness/meeting_result.json").read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    for i, s in enumerate(segs):
        s.setdefault("index", i)
    return segs


def ref_chapters_by_time(mid):
    """golden_v2 fine_chapters → 带 start_ms/end_ms 的章节区间(按时间)。"""
    g = json.loads((ROOT / f"eval/golden_v2/out/{mid}.golden.json").read_text(encoding="utf-8"))
    fc = sorted((g.get("fine_chapters") or []), key=lambda c: c.get("start_s") or 0)
    chapters = []
    for i, c in enumerate(fc):
        start_s = c.get("start_s")
        end_s = c.get("end_s")
        if end_s is None:  # 缺 end 用下一章起点兜底
            end_s = fc[i + 1].get("start_s") if i + 1 < len(fc) else (start_s or 0) + 1
        if start_s is None:
            continue
        chapters.append({"chapter_id": c.get("id") or f"F{i}",
                         "start_ms": int(start_s * 1000), "end_ms": int(end_s * 1000)})
    return chapters, len(fc)


def boundaries(labels):
    """标签序列的内部边界位置集合(label 变化处，位置0不算)。"""
    return {i for i in range(1, len(labels)) if labels[i] != labels[i - 1]}


def main():
    tol = 1
    rows = []
    for tag, mid in CASES:
        segs = load_board_segments(tag)
        chapters, n_fc = ref_chapters_by_time(mid)
        ref_labels = labels_from_time_chapters(segs, chapters)

        policy = BudgetPolicy(ctx=16384, output_tokens=3072, chars_per_token=1.55)
        blocks = segment_blocks(segs, policy, SegmentationConfig())["blocks"]
        id_to_index = {str(s["segment_id"]): s["index"] for s in segs}
        seg_block = {}
        for bi, b in enumerate(blocks):
            for sid in (b.get("segment_ids") or []):
                seg_block[str(sid)] = bi
        hyp_labels = [f"a{seg_block.get(str(s['segment_id']), -1)}" for s in segs]

        # 裁到银标覆盖区间(ref 非 None)
        keep = [i for i, r in enumerate(ref_labels) if r is not None]
        ref = [ref_labels[i] for i in keep]
        hyp = [hyp_labels[i] for i in keep]
        if len(ref) < 3:
            print(f"[{tag}/{mid}] 参考覆盖过少，跳过"); continue

        ref_b, hyp_b = boundaries(ref), boundaries(hyp)
        hit = sum(1 for g in ref_b if any(abs(g - h) <= tol for h in hyp_b))
        recall = hit / len(ref_b) if ref_b else 1.0
        prec = (sum(1 for h in hyp_b if any(abs(h - g) <= tol for g in ref_b)) / len(hyp_b)) if hyp_b else 0.0
        k = boundary_k(ref)
        p, wd = pk(ref, hyp, k), window_diff(ref, hyp, k)
        rows.append((tag, mid, n_fc, len(blocks), len(ref), recall, prec, p, wd))
        print(f"[{tag}] {mid}  银标章={n_fc} A层块={len(blocks)}(N={len(ref)})  "
              f"边界召回={recall:.2f}({hit}/{len(ref_b)}) 精确={prec:.2f}  Pk={p:.3f} WD={wd:.3f}")

    if rows:
        n = len(rows)
        mr = sum(r[5] for r in rows) / n
        mp = sum(r[6] for r in rows) / n
        mpk = sum(r[7] for r in rows) / n
        mwd = sum(r[8] for r in rows) / n
        avg_over = sum(r[3] / max(r[2], 1) for r in rows) / n
        print("=" * 66)
        print(f"均值(n={n}场): 边界召回={mr:.2f}  精确={mp:.2f}  Pk={mpk:.3f}  WindowDiff={mwd:.3f}  "
              f"过切倍率(A层块/银标章)={avg_over:.2f}x")
        print("解读: A层刻意过切→召回应高(合并层只需归并)/Pk偏高属预期; "
              "参考为银标(fable5+opus5)非人工gold、按时间对齐, 绝对值仅供多场一致性判断。")


if __name__ == "__main__":
    main()
