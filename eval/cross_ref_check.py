#!/usr/bin/env python3
"""跨章指代检测:当前 ASR 转写 + 分章策略下,是否存在"章节开头的指代词,
其指代对象只在上一章、本章内找不到"(跨章悬空指代)。

用 qwen-max 逐章做语篇分析(比 4b 准)。对每个 i>=1 的章:
给本章全文,判断是否有'这个/那个/它/他们/上述…'等指代在本章内无法解析(需依赖上一章)。
统计:含跨章悬空指代的章 / 章节交界总数 = 跨章指代发生率。

前提:board meeting_result.json(transcript+summary.chapters)。默认 g1-g5。
用法(先设 DASHSCOPE_API_KEY):
  python eval/cross_ref_check.py --out eval/reports/cross_ref
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
DEFAULT_MEETINGS = [BOARD / f"{g}/harness/meeting_result.json" for g in ("g1", "g2", "g3", "g4", "g5")]

BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.8-max"
SYS = ("你是中文会议语篇分析助手。给你会议某一章的文本,判断其中是否存在指代表达"
       "(这个/那个/它/他/他们/这些/那些/上述/该…),其指代对象在【本章文本内】找不到、"
       "必须依赖上一章才能理解(=跨章悬空指代)。\n"
       "严格:只算本章内确实找不到所指对象的;能在本章内(哪怕后文)找到所指的不算;"
       "泛指/习惯用语(如'这个'作口头停顿)不算。\n"
       '只输出JSON:{"cross_refs":[{"expr":"指代词及其所在短句","why":"为何本章内无法解析"}]}。')


def chapters(mr: Path):
    d = json.loads(mr.read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    idx = {s["segment_id"]: i for i, s in enumerate(segs)}
    out = []
    for ch in (d.get("summary") or {}).get("chapters") or []:
        a, b = ch.get("start_ref"), ch.get("end_ref")
        m = segs[idx[a]: idx[b] + 1] if a in idx and b in idx else []
        out.append((ch.get("title", ""), "".join((s.get("text") or "").strip() for s in m if (s.get("text") or "").strip())))
    return out


def ask(text: str) -> list:
    key = os.environ["DASHSCOPE_API_KEY"]
    body = json.dumps({"model": MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": SYS},
                                    {"role": "user", "content": "【本章文本】\n" + text[:2500]}]}).encode("utf-8")
    req = urllib.request.Request(BASE + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as h:
            r = json.loads(h.read().decode("utf-8"))
        c = r["choices"][0]["message"]["content"]
        return (json.loads(c) or {}).get("cross_refs", [])
    except Exception as e:  # noqa: BLE001
        print("  裁判失败:", repr(e)[:100]); return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "cross_ref")
    ap.add_argument("--meetings", nargs="*", type=Path, default=DEFAULT_MEETINGS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tot_bound = tot_cross = 0
    rows = []
    for mr in args.meetings:
        if not mr.exists():
            print("跳过(不存在):", mr); continue
        chs = chapters(mr)
        name = mr.parts[-3]
        n_bound = max(0, len(chs) - 1)
        hits = []
        for i in range(1, len(chs)):  # i>=1 才有"上一章"
            title, text = chs[i]
            crs = ask(text)
            if crs:
                hits.append({"chapter": i, "title": title, "cross_refs": crs})
            print(f"[{name}] ch{i} 《{title[:12]}》 跨章指代={len(crs)}")
        tot_bound += n_bound
        tot_cross += len(hits)
        rows.append({"meeting": name, "chapters": len(chs), "boundaries": n_bound,
                     "chapters_with_cross_ref": len(hits), "detail": hits})

    rate = round(tot_cross / tot_bound, 3) if tot_bound else 0.0
    (args.out / "cross_ref.json").write_text(json.dumps({"rate": rate, "total_boundaries": tot_bound,
        "chapters_with_cross_ref": tot_cross, "meetings": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n==== 汇总 ====")
    print(f"会议数={len([r for r in rows])}  章节交界总数={tot_bound}  含跨章指代的章={tot_cross}")
    print(f"跨章指代发生率 = {rate}  ({tot_cross}/{tot_bound})")
    # 列出所有检出的跨章指代供人核对
    for r in rows:
        for h in r["detail"]:
            for cr in h["cross_refs"]:
                print(f"  [{r['meeting']} ch{h['chapter']}] 「{cr.get('expr','')[:40]}」 — {cr.get('why','')[:50]}")


if __name__ == "__main__":
    main()
