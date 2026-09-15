"""本机 A0 复算召回:用板端同一份转写,只换 A0 单章摘要(Ollama qwen3:4b),对新金标算 core_fact 召回。

与板上 pre-A0 严格同输入(同转写、同章节切分),只变摘要方案 → 隔离 A0 的增益。
用法: python pc_a0_recall.py <board_meeting_result.json> <golden.json>
"""
from __future__ import annotations
import json, sys, pathlib

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval" / "golden_v2"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession  # noqa: E402
from meeting_agent.stages.product_summary import (  # noqa: E402
    _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map)
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE  # noqa: E402
from meeting_agent.stages.validation import parse_content  # noqa: E402
import score_candidate as SC  # noqa: E402


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
    outdir = ROOT / "eval" / "golden_v2" / "_pc_a0"
    session = OllamaSession(OllamaConfig(model="qwen3:4b", max_tokens=900), outdir)
    session.out_dir = outdir
    summaries = []
    for i, seg in enumerate(chaps):
        rm, _ = _build_compact_ref_map(seg)
        sm, _ = _build_compact_speaker_map([s.get("speaker_id", "") for s in seg])
        msgs = _block_summary_messages(seg, None, ref_map=rm, speaker_map=sm, profile=GENERIC_PROFILE)
        r = session.request(msgs, outdir / f"ch{i}", max_tokens=900, request_kind="a0pc")
        raw = parse_content(r.get("content", "")) or {}
        summaries.append(str(raw.get("summary", "")).strip())
        print(f"  ch{i} done ({len(summaries[-1])}字)", flush=True)
    cand = SC.norm(" ".join(summaries))
    g = json.loads(pathlib.Path(gold).read_text(encoding="utf-8"))
    res = SC.score(g, cand)
    print("A0(PC) 章节=%d  核心事实召回=%s (%d/%d)  低频=%s(%s)" % (
        len(chaps), res["core_fact_recall"], res["recalled"], res["total"],
        res["lowfreq_recall"], res["lowfreq"]))
    print("漏项:", [(m["id"], m["text"][:20]) for m in res["missed"]])


if __name__ == "__main__":
    main()
