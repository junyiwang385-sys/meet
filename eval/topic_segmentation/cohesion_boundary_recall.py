#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：字符 bigram vs 句向量 —— 谁能把人工金标准边界"切"出来。

对同一场会算两种相邻内聚度曲线，各取"最深的前 K 个低谷"作为预测边界，
对金标准内部边界算召回（±tol 段容差）。回答核心问题：
  新方法 Pk 变差，是"确定性方法本身不行"，还是"字符内聚信号太弱"？
若句向量召回明显高于字符法，则结论是后者：把内聚函数换成句向量即可修。

依赖：numpy, fastembed（CPU）。
用法（meet 根目录）：
  PYTHONIOENCODING=utf-8 python eval/topic_segmentation/cohesion_boundary_recall.py \
      --segments "E:/task-2a83a3a8a98a/harness/03_llm_summary/canonical_segments.json"
"""
import argparse
import json
import math
import os
from collections import Counter

import numpy as np


def bigrams(t):
    t = "".join(t.split())
    return Counter(t[i:i + 2] for i in range(len(t) - 1)) if len(t) >= 2 else Counter([t] if t else [])


def cos_counter(a, b):
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    if dot == 0:
        return 0.0
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def depths(coh, n, W=4):
    d = [0.0] * n
    for i in range(1, n):
        if coh[i] is None:
            continue
        l = next((coh[j] for j in range(i - 1, 0, -1) if coh[j] is not None), None)
        r = next((coh[j] for j in range(i + 1, n) if coh[j] is not None), None)
        if (l is not None and l < coh[i]) or (r is not None and r < coh[i]):
            continue
        left = [coh[j] for j in range(max(1, i - W), i) if coh[j] is not None]
        right = [coh[j] for j in range(i + 1, min(n, i + 1 + W)) if coh[j] is not None]
        lp = max(left) if left else coh[i]
        rp = max(right) if right else coh[i]
        d[i] = max(0.0, lp - coh[i]) + max(0.0, rp - coh[i])
    return d


def topN(d, n, N):
    return sorted(sorted([i for i in range(1, n) if d[i] > 0], key=lambda i: -d[i])[:N])


def recall(pred, gold, tol):
    hit = sum(1 for g in gold if any(abs(g - p) <= tol for p in pred))
    return hit, hit / len(gold) if gold else 1.0


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", required=True)
    ap.add_argument("--golden", default=os.path.join(here, "golden_mtg_9c6133819814365e.json"))
    ap.add_argument("--K", type=int, default=10)
    ap.add_argument("--tol", type=int, default=1)
    args = ap.parse_args()

    raw = json.load(open(args.segments, encoding="utf-8"))
    segs = raw["segments"] if isinstance(raw, dict) and "segments" in raw else raw
    segs = [s for s in segs if str(s.get("text") or "").strip()]
    # 用 canonical 的 index 对齐金标准（金标准按原始 index 标注）
    idx = [s.get("index") for s in segs]
    texts = [s["text"] for s in segs]
    n = len(segs)

    golden = json.load(open(args.golden, encoding="utf-8"))
    gold_starts = sorted(c["start_index"] for c in golden["chapters"])
    gold_internal = [g for g in gold_starts if g != gold_starts[0]]

    # 映射：原始 index -> canonical 位置
    pos_of_index = {v: i for i, v in enumerate(idx)}

    def to_pos(index_list):
        out = []
        for g in index_list:
            # 金标准边界 index 可能是空段，取最近的非空 canonical 位置
            if g in pos_of_index:
                out.append(pos_of_index[g])
            else:
                cand = [pos_of_index[k] for k in pos_of_index if abs(k - g) <= 2]
                if cand:
                    out.append(min(cand, key=lambda p: abs(idx[p] - g)))
        return sorted(set(out))

    gold_pos = to_pos(gold_internal)

    K = 3
    # 字符法
    char_coh = [None] * n
    for i in range(1, n):
        lo = Counter()
        for j in range(max(0, i - K), i):
            lo += bigrams(texts[j])
        hi = Counter()
        for j in range(i, min(n, i + K)):
            hi += bigrams(texts[j])
        char_coh[i] = cos_counter(lo, hi)
    char_pred = topN(depths(char_coh, n), n, args.K)

    # 句向量
    from fastembed import TextEmbedding
    model = TextEmbedding("BAAI/bge-small-zh-v1.5")
    embs = np.array(list(model.embed(texts)))
    emb_coh = [None] * n
    for i in range(1, n):
        a = embs[max(0, i - K):i].mean(axis=0)
        b = embs[i:min(n, i + K)].mean(axis=0)
        emb_coh[i] = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    emb_pred = topN(depths(emb_coh, n), n, args.K)

    hc, rc = recall(char_pred, gold_pos, args.tol)
    he, re_ = recall(emb_pred, gold_pos, args.tol)

    print("=" * 64)
    print(f"金标准内部边界(canonical位置) = {gold_pos}  (共 {len(gold_pos)})")
    print(f"字符bigram 最深{args.K}谷 = {char_pred}")
    print(f"句向量bge  最深{args.K}谷 = {emb_pred}")
    print("-" * 64)
    print(f"[字符bigram] 金标准边界召回(±{args.tol}) = {hc}/{len(gold_pos)} = {rc:.2f}")
    print(f"[句向量bge ] 金标准边界召回(±{args.tol}) = {he}/{len(gold_pos)} = {re_:.2f}")
    print("=" * 64)
    print("结论：若句向量召回显著更高 → 不是'确定性方法不行'，是'字符内聚信号太弱'，")
    print("      把 A 层内聚函数换成句向量即可修（与 0.18 vs 0.76 内聚实验同一根因）。")


if __name__ == "__main__":
    main()
