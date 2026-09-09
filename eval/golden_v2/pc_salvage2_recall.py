"""A0 摘要 + 确定性数字打捞 + 低频专名打捞(jieba,只抽出现<=maxfreq次的名词类,防灌水)。
用法: python pc_salvage2_recall.py <board_meeting_result.json> <golden.json>
"""
from __future__ import annotations
import json, re, sys, pathlib
from collections import Counter

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "eval" / "golden_v2"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession  # noqa: E402
from meeting_agent.stages.product_summary import (  # noqa: E402
    _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map)
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE  # noqa: E402
from meeting_agent.stages.validation import parse_content  # noqa: E402
import score_candidate as SC  # noqa: E402
import jieba.posseg as pseg  # noqa: E402

_NUM = re.compile(r"[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万亿]{1,}")
_CJK = re.compile(r"[一-鿿]")
NOUN = {"n", "nr", "ns", "nt", "nz", "nrt", "nrfg", "l", "i", "j", "an", "nl", "ng"}


def salvage_numbers(text, win=7):
    out, seen = [], set()
    for m in _NUM.finditer(text):
        span = text[max(0, m.start() - win):min(len(text), m.end() + win)].strip()
        if span not in seen:
            seen.add(span); out.append(span)
    return out


def salvage_entities(text, maxfreq=3):
    toks = [w for w, f in pseg.cut(text) if f in NOUN and len(w) >= 2 and _CJK.search(w)]
    cnt = Counter(toks)
    return sorted({w for w in toks if cnt[w] <= maxfreq})  # 低频 distinctive


def chapters(mr):
    d = json.loads(pathlib.Path(mr).read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    idx = {s["segment_id"]: i for i, s in enumerate(segs)}
    out = []
    for ch in (d.get("summary") or {}).get("chapters") or []:
        a, b = ch.get("start_ref"), ch.get("end_ref")
        m = segs[idx[a]:idx[b] + 1] if a in idx and b in idx else []
        out.append([s for s in m if (s.get("text") or "").strip()])
    return out


def main():
    mr, gold = sys.argv[1], sys.argv[2]
    chaps = chapters(mr)
    outdir = ROOT / "eval" / "golden_v2" / "_pc_salv2"
    session = OllamaSession(OllamaConfig(model="qwen3:4b", max_tokens=900), outdir)
    session.out_dir = outdir
    summaries, nums, ents = [], [], []
    full = "".join("".join((s.get("text") or "") for s in seg) for seg in chaps)
    ents = salvage_entities(full)  # 全场低频专名
    for i, seg in enumerate(chaps):
        rm, _ = _build_compact_ref_map(seg)
        sm, _ = _build_compact_speaker_map([s.get("speaker_id", "") for s in seg])
        msgs = _block_summary_messages(seg, None, ref_map=rm, speaker_map=sm, profile=GENERIC_PROFILE)
        r = session.request(msgs, outdir / f"ch{i}", max_tokens=900, request_kind="salv2")
        raw = parse_content(r.get("content", "")) or {}
        summaries.append(str(raw.get("summary", "")).strip())
        nums += salvage_numbers("".join((s.get("text") or "") for s in seg))
        print(f"  ch{i} done", flush=True)
    g = json.loads(pathlib.Path(gold).read_text(encoding="utf-8"))
    base = " ".join(summaries)
    r_a0 = SC.score(g, SC.norm(base))
    r_n = SC.score(g, SC.norm(base + " " + " ".join(nums)))
    r_ne = SC.score(g, SC.norm(base + " " + " ".join(nums) + " " + " ".join(ents)))
    print("A0           召回=%s(%d/%d) 低频=%s" % (r_a0["core_fact_recall"], r_a0["recalled"], r_a0["total"], r_a0["lowfreq"]))
    print("+数字        召回=%s(%d/%d) 低频=%s" % (r_n["core_fact_recall"], r_n["recalled"], r_n["total"], r_n["lowfreq"]))
    print("+数字+专名   召回=%s(%d/%d) 低频=%s  (专名词数=%d)" % (
        r_ne["core_fact_recall"], r_ne["recalled"], r_ne["total"], r_ne["lowfreq"], len(ents)))
    print("仍漏:", [(m["id"], m["text"][:16]) for m in r_ne["missed"]])


if __name__ == "__main__":
    main()
