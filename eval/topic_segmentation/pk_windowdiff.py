#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""话题分章评测：Pk / WindowDiff（越低越好）。

对照对象：
  - golden : 人工金标准（本目录 golden_*.json，按 segment index 区间标注章节）
  - old    : 旧 temperature=0 网关结果 result.json（每段带 chapter_id，或 chapters[] 带 ms 区间）
  - new    : 新方法产出的 chapters.json（网关 v1 chapters[] 或每段 chapter_id 均可）

评测单元：金标准覆盖的连续段区间（默认 seg2..seg172），忽略首尾空段。
Pk/WindowDiff 都在“段序列的相邻间隙”上滑窗，k 取参考段长均值的一半（标准做法）。

依赖：仅标准库。

用法：
  python pk_windowdiff.py \
      --golden golden_mtg_9c6133819814365e.json \
      --old   C:/Users/Admin/Downloads/result.json \
      [--new  path/to/new_chapters.json] \
      [--segments C:/Users/Admin/Downloads/result.json]  # 段序列来源，默认取 --old
"""
import argparse
import json
import os


# ---------- 载入段序列（有序、带 index/start_ms/end_ms） ----------
def load_segments(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tr = data.get("transcript", data)
    segs = tr["segments"] if isinstance(tr, dict) and "segments" in tr else tr
    out = []
    for s in segs:
        out.append({
            "index": s.get("index"),
            "segment_id": s.get("segment_id"),
            "start_ms": s.get("start_ms"),
            "end_ms": s.get("end_ms"),
            "chapter_id": s.get("chapter_id"),
        })
    out.sort(key=lambda x: (x["start_ms"] if x["start_ms"] is not None else 0))
    # 若无 index，用排序序补齐
    for i, s in enumerate(out):
        if s["index"] is None:
            s["index"] = i
    return out


# ---------- 三种来源 -> 每段章节标签 ----------
def labels_from_segment_chapter_id(segments):
    """旧网关：每段自带 chapter_id。None 视为无归属。"""
    return [s["chapter_id"] for s in segments]


def labels_from_time_chapters(segments, chapters):
    """chapters[] 带 start_ms/end_ms：按段中点落入哪个章节区间赋标签。"""
    spans = []
    for i, c in enumerate(chapters):
        cid = c.get("chapter_id") or c.get("id")
        if not cid:
            cid = f"c{i}"  # 无 id 时按顺序编号，避免全部塌成同一标签
        spans.append((c.get("start_ms"), c.get("end_ms"), cid))
    labels = []
    for s in segments:
        mid = (s["start_ms"] + (s["end_ms"] if s["end_ms"] is not None else s["start_ms"])) / 2
        lab = None
        for a, b, cid in spans:
            if a is None or b is None:
                continue
            if a <= mid <= b:
                lab = cid
                break
        labels.append(lab)
    return labels


def labels_from_golden(segments, golden):
    """金标准：按 segment index 区间 [start_index, end_index] 赋标签。"""
    ranges = [(c["start_index"], c["end_index"], c["chapter_id"]) for c in golden["chapters"]]
    labels = []
    for s in segments:
        idx = s["index"]
        lab = None
        for a, b, cid in ranges:
            if a <= idx <= b:
                lab = cid
                break
        labels.append(lab)
    return labels


def load_chapters_generic(segments, path):
    """new/old 通用：优先每段 chapter_id，否则用 chapters[] 时间区间。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # 情况 0：裸 chapters 列表（如 03_llm_summary/chapters.json）
    if isinstance(data, list):
        return labels_from_time_chapters(segments, data)
    # 情况 A：本身就是 result.json，段里有 chapter_id
    tr = data.get("transcript")
    if isinstance(tr, dict) and tr.get("segments") and any(
            x.get("chapter_id") for x in tr["segments"]):
        by_id = {x.get("segment_id"): x.get("chapter_id") for x in tr["segments"]}
        return [by_id.get(s["segment_id"]) for s in segments]
    # 情况 B：有 chapters[] 时间区间
    chapters = data.get("chapters") or (data if isinstance(data, list) else None)
    if chapters:
        return labels_from_time_chapters(segments, chapters)
    raise ValueError(f"无法从 {path} 解析章节（既无段级 chapter_id，也无 chapters[]）。")


# ---------- 评测：把标签序列裁到金标准覆盖区间 ----------
def restrict_to_reference(ref_labels, *others):
    """保留 ref 非 None 的位置，返回同长度裁剪后的多个序列。"""
    keep = [i for i, r in enumerate(ref_labels) if r is not None]
    ref = [ref_labels[i] for i in keep]
    outs = [[o[i] for i in keep] for o in others]
    return ref, outs


def num_segments(labels):
    return 1 + sum(1 for i in range(1, len(labels)) if labels[i] != labels[i - 1])


def boundary_k(ref_labels):
    n = len(ref_labels)
    segs = num_segments(ref_labels)
    return max(2, int(round(n / (2.0 * segs))))


def pk(ref, hyp, k):
    n = len(ref)
    err = 0
    total = 0
    for i in range(0, n - k):
        total += 1
        same_ref = ref[i] == ref[i + k]
        same_hyp = hyp[i] == hyp[i + k]
        if same_ref != same_hyp:
            err += 1
    return err / total if total else 0.0


def window_diff(ref, hyp, k):
    n = len(ref)
    rb = [1 if ref[i] != ref[i + 1] else 0 for i in range(n - 1)]
    hb = [1 if hyp[i] != hyp[i + 1] else 0 for i in range(n - 1)]
    err = 0
    total = 0
    for i in range(0, n - k):
        total += 1
        rc = sum(rb[i:i + k])
        hc = sum(hb[i:i + k])
        if rc != hc:
            err += 1
    return err / total if total else 0.0


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--golden", default=os.path.join(here, "golden_mtg_9c6133819814365e.json"))
    ap.add_argument("--old", default=r"C:/Users/Admin/Downloads/result.json")
    ap.add_argument("--new", default=None)
    ap.add_argument("--segments", default=None,
                    help="段序列来源(带时间/index)。默认取 --old")
    args = ap.parse_args()

    seg_src = args.segments or args.old
    segments = load_segments(seg_src)

    with open(args.golden, encoding="utf-8") as f:
        golden = json.load(f)
    gold = labels_from_golden(segments, golden)

    old = load_chapters_generic(segments, args.old)
    new = load_chapters_generic(segments, args.new) if args.new else None

    others = [old] + ([new] if new is not None else [])
    ref, cut = restrict_to_reference(gold, *others)
    old_c = cut[0]
    new_c = cut[1] if new is not None else None

    k = boundary_k(ref)
    n = len(ref)

    print("=" * 60)
    print(f"评测单元数 N = {n}（金标准覆盖段）")
    print(f"金标准章节数 = {num_segments(ref)}，滑窗 k = {k}")
    print(f"旧方法章节数 = {num_segments(old_c)}"
          + (f"，新方法章节数 = {num_segments(new_c)}" if new_c else ""))
    print("=" * 60)

    def report(name, hyp):
        print(f"[{name}]  Pk = {pk(ref, hyp, k):.3f}   WindowDiff = {window_diff(ref, hyp, k):.3f}")

    report("old vs golden", old_c)
    if new_c is not None:
        report("new vs golden", new_c)
    # 上界参照：全无边界（把整场当一章）
    flat = [ref[0]] * n
    report("no-boundary baseline", flat)
    print("（Pk/WindowDiff 越低越好；no-boundary 基线用于参照上界）")


if __name__ == "__main__":
    main()
