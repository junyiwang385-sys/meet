#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实验：话语标记(discourse cue)边界检测，重切并对金标准评测。

假设：本会真话题边界由"主持人交接 / 学员提问开场 / 讲师收尾总结"这类话语标记触发，
而非词汇/语义内聚。故用纯 CPU 正则+轮次特征检测这些标记作为边界，验证能否补回
seg65/71/92/115/126/161 这几条被 cohesion/gap 漏掉的尾部边界。

可选 --with-cohesion：在无话语标记的区段补 top-N 字符内聚深谷，兼顾前半的内容型边界(28/33/54)。

依赖：仅标准库(+numpy 若开 cohesion)。
用法(meet 根目录)：
  PYTHONIOENCODING=utf-8 python eval/topic_segmentation/discourse_segmenter.py \
      --segments "E:/task-2a83a3a8a98a/harness/03_llm_summary/canonical_segments.json" [--with-cohesion]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pk_windowdiff import num_segments, boundary_k, pk, window_diff  # noqa: E402

# 学员提问开场（边界置于该段）
QOPEN = re.compile(
    r"我这边儿?想问一?下?|我想问|我那?我?想知道|我有一个(看法|问题|想法)|我现在手里有|"
    r"我这边儿?想问"
)
# 主持人/讲师邀请下一位（边界置于其后的首个实质段）
INVITE = re.compile(
    r"大家有没有.{0,8}问题|还有其?他?.{0,4}问题吗|来下一位|下一位|下一个问题|"
    r"抓紧时间先回答|咱先.{0,6}回答"
)
# 收尾/总结（边界置于该段）
SUMMARY = re.compile(r"进行一?个?.{0,8}总结|给咱们.{0,6}总结|做一个总结|咱们毕业吧|本场.{0,8}结束|到此结束")
# 开场（讲师宣布培训，边界置于该段）
LOPEN = re.compile(r"今天.{0,12}培训")

SUBSTANTIVE_MIN = 12  # “实质段”最小字数


def load_segs(path):
    raw = json.load(open(path, encoding="utf-8"))
    segs = raw["segments"] if isinstance(raw, dict) and "segments" in raw else raw
    out = []
    for i, s in enumerate(segs):
        out.append({
            "index": s.get("index", i),
            "segment_id": s.get("segment_id"),
            "speaker_id": s.get("speaker_id"),
            "text": str(s.get("text") or ""),
            "start_ms": s.get("start_ms"),
        })
    return out


def next_substantive(segs, i):
    for j in range(i + 1, len(segs)):
        if len(segs[j]["text"].strip()) >= SUBSTANTIVE_MIN:
            return j
    return None


def detect_discourse(segs):
    """返回边界起点的 original index 集合 + 触发原因。"""
    reasons = {}  # orig_index -> reason
    for i, s in enumerate(segs):
        t = s["text"]
        if not t.strip():
            continue
        if LOPEN.search(t):
            reasons.setdefault(s["index"], "lecture_open")
        if QOPEN.search(t):
            reasons.setdefault(s["index"], "question_open")
        if SUMMARY.search(t):
            reasons.setdefault(s["index"], "summary")
        if INVITE.search(t):
            j = next_substantive(segs, i)
            if j is not None:
                reasons.setdefault(segs[j]["index"], "invite_next")
    return reasons


def add_cohesion(segs, existing_indices, topn=3):
    """在无话语标记的区段补字符内聚深谷（前半内容型边界）。"""
    import math
    from collections import Counter

    ne = [s for s in segs if s["text"].strip()]
    texts = [s["text"] for s in ne]
    n = len(ne)
    K = 3

    def bg(t):
        t = "".join(t.split())
        return Counter(t[k:k + 2] for k in range(len(t) - 1)) if len(t) >= 2 else Counter()

    def cos(a, b):
        common = set(a) & set(b)
        d = sum(a[k] * b[k] for k in common)
        if d == 0:
            return 0.0
        return d / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))

    coh = [None] * n
    for i in range(1, n):
        lo = Counter()
        for j in range(max(0, i - K), i):
            lo += bg(texts[j])
        hi = Counter()
        for j in range(i, min(n, i + K)):
            hi += bg(texts[j])
        coh[i] = cos(lo, hi)
    W = 4
    depth = [0.0] * n
    for i in range(1, n):
        if coh[i] is None:
            continue
        left = [coh[j] for j in range(max(1, i - W), i) if coh[j] is not None]
        right = [coh[j] for j in range(i + 1, min(n, i + 1 + W)) if coh[j] is not None]
        lp = max(left) if left else coh[i]
        rp = max(right) if right else coh[i]
        depth[i] = max(0.0, lp - coh[i]) + max(0.0, rp - coh[i])
    order = sorted(range(1, n), key=lambda i: -depth[i])
    added = {}
    used = set(existing_indices)
    for i in order:
        if depth[i] <= 0:
            break
        idx = ne[i]["index"]
        if any(abs(idx - u) <= 3 for u in used):
            continue
        added[idx] = "cohesion_valley"
        used.add(idx)
        if len(added) >= topn:
            break
    return added


def labels_over_range(segs, boundary_indices, lo, hi):
    """对 index 在 [lo,hi] 的段，按边界起点赋章节标签。"""
    bset = set(boundary_indices)
    labels = []
    chap = -1
    for s in segs:
        if s["index"] < lo or s["index"] > hi:
            continue
        if s["index"] in bset or chap == -1:
            chap += 1
        labels.append(chap)
    return labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", required=True)
    ap.add_argument("--golden", default=os.path.join(HERE, "golden_mtg_9c6133819814365e.json"))
    ap.add_argument("--with-cohesion", action="store_true")
    ap.add_argument("--tol", type=int, default=1)
    args = ap.parse_args()

    segs = load_segs(args.segments)
    golden = json.load(open(args.golden, encoding="utf-8"))
    gold_starts = sorted(c["start_index"] for c in golden["chapters"])
    lo, hi = gold_starts[0], max(c["end_index"] for c in golden["chapters"])
    gold_internal = [g for g in gold_starts if g != gold_starts[0]]

    reasons = detect_discourse(segs)
    if args.with_cohesion:
        reasons.update(add_cohesion(segs, set(reasons), topn=3))

    # 确保首章起点存在
    starts = sorted(set(list(reasons.keys()) + [lo]))
    starts = [s for s in starts if lo <= s <= hi]
    internal = [s for s in starts if s != lo]
    # 后处理：合并过近边界(<min_gap)只留首个；去掉贴近尾部的琐碎边界。
    min_gap = 3
    merged = []
    for b in internal:
        if merged and b - merged[-1] < min_gap:
            continue
        if b > hi - 2:  # 末尾 1-2 段不再单开一章
            continue
        merged.append(b)
    internal = merged

    # 边界召回
    hit = [g for g in gold_internal if any(abs(g - a) <= args.tol for a in internal)]
    recall = len(hit) / len(gold_internal)

    # Pk / WindowDiff
    ref_labels = labels_over_range(
        [{"index": g["start_index"], "text": "x"} for g in _expand_golden(golden)], None, lo, hi
    ) if False else None
    # 直接用 golden 区间构造 ref 标签
    gold_ranges = [(c["start_index"], c["end_index"], c["chapter_id"]) for c in golden["chapters"]]

    def gold_label(idx):
        for a, b, cid in gold_ranges:
            if a <= idx <= b:
                return cid
        return None

    seg_idx = [s["index"] for s in segs if lo <= s["index"] <= hi]
    ref = [gold_label(i) for i in seg_idx]
    hyp = labels_over_range(segs, internal, lo, hi)
    # 对齐长度
    m = min(len(ref), len(hyp))
    ref, hyp = ref[:m], hyp[:m]
    k = boundary_k(ref)

    print("=" * 66)
    print(f"话语标记边界(reason): ")
    for idx in sorted(reasons):
        if lo <= idx <= hi:
            print(f"   seg{idx:>3}  {reasons[idx]:14s}  {_text_of(segs, idx)[:30]}")
    print("-" * 66)
    print(f"预测内部边界 index = {internal}")
    print(f"金标准内部边界 index = {gold_internal}")
    print(f"命中(±{args.tol}) = {sorted(hit)}  → 召回 {len(hit)}/{len(gold_internal)} = {recall:.2f}")
    print("-" * 66)
    print(f"章节数: 预测 {num_segments(hyp)}  vs 金标准 {len(golden['chapters'])}")
    print(f"[discourse{'+cohesion' if args.with_cohesion else ''} vs golden]  "
          f"Pk = {pk(ref, hyp, k):.3f}   WindowDiff = {window_diff(ref, hyp, k):.3f}   (N={m}, k={k})")
    print("对照：老0.350 / 新(A层)0.497 / 不分章0.460")


def _text_of(segs, idx):
    for s in segs:
        if s["index"] == idx:
            return s["text"]
    return ""


def _expand_golden(g):
    return g["chapters"]


if __name__ == "__main__":
    main()
