"""A0 摘要 + 确定性正则数字打捞,对新金标算召回。
数字/金额/日期用正则从转写抽(带上下文窗口),强制拼进候选;确定性、不占模型输出、无噪声。
用法: python pc_salvage_recall.py <board_meeting_result.json> <golden.json>
"""
from __future__ import annotations
import json, re, sys, pathlib

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "eval" / "golden_v2"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession  # noqa: E402
from meeting_agent.stages.product_summary import (  # noqa: E402
    _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map)
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE  # noqa: E402
from meeting_agent.stages.validation import parse_content  # noqa: E402
import score_candidate as SC  # noqa: E402

_NUM = re.compile(r"[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万亿]{1,}")


def salvage_numbers(text: str, win: int = 7) -> list[str]:
    """抽每个数字 token 及左右 win 字上下文,去重。"""
    out, seen = [], set()
    for m in _NUM.finditer(text):
        a, b = max(0, m.start() - win), min(len(text), m.end() + win)
        span = text[a:b].strip()
        if span not in seen:
            seen.add(span); out.append(span)
    return out


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
    outdir = ROOT / "eval" / "golden_v2" / "_pc_salv"
    session = OllamaSession(OllamaConfig(model="qwen3:4b", max_tokens=900), outdir)
    session.out_dir = outdir
    summaries, salv = [], []
    for i, seg in enumerate(chaps):
        rm, _ = _build_compact_ref_map(seg)
        sm, _ = _build_compact_speaker_map([s.get("speaker_id", "") for s in seg])
        msgs = _block_summary_messages(seg, None, ref_map=rm, speaker_map=sm, profile=GENERIC_PROFILE)
        r = session.request(msgs, outdir / f"ch{i}", max_tokens=900, request_kind="salv")
        raw = parse_content(r.get("content", "")) or {}
        summaries.append(str(raw.get("summary", "")).strip())
        blocktext = "".join((s.get("text") or "").strip() for s in seg)
        salv += salvage_numbers(blocktext)
        print(f"  ch{i} done", flush=True)
    g = json.loads(pathlib.Path(gold).read_text(encoding="utf-8"))
    r_a0 = SC.score(g, SC.norm(" ".join(summaries)))
    r_sv = SC.score(g, SC.norm(" ".join(summaries) + " " + " ".join(salv)))
    print("A0 仅摘要   召回=%s(%d/%d) 低频=%s" % (r_a0["core_fact_recall"], r_a0["recalled"], r_a0["total"], r_a0["lowfreq"]))
    print("A0+数字打捞 召回=%s(%d/%d) 低频=%s" % (r_sv["core_fact_recall"], r_sv["recalled"], r_sv["total"], r_sv["lowfreq"]))
    print("打捞片段数=%d  仍漏:" % len(set(salv)), [(m["id"], m["text"][:16]) for m in r_sv["missed"]])


if __name__ == "__main__":
    main()
