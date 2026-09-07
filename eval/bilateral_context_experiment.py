#!/usr/bin/env python3
"""A3b 双侧上下文 vs A0 单段 —— 用【项目生产提示词】(_block_summary_messages)。

A3b:取连续三章,为【中间章】生成摘要,把前一章+后一章作为只读参考上下文(双侧)。
A0 :同一中间章,单独摘要,无上下文(基线)。
两组都复用 product_summary 的生产 block-summary 提示词(先抽key_points→anchors→summary),
滑窗遍历每个可作中间章的章(i=1..n-2),对比摘要质量。

指标:关键点召回(对金标)、串味率(refs 落到中间章之外)、摘要字数。

用法(Ollama 在跑):
  python eval/bilateral_context_experiment.py --meeting-result <g2.json> --golden eval/golden/R002S05C01.keypoints.json --out eval/reports/a3b_g2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval" / "summary"))

from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession   # noqa: E402
from meeting_agent.stages.product_summary import (                          # noqa: E402
    _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map,
    _render_compact_timeline,
)
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE           # noqa: E402
from meeting_agent.stages.validation import parse_content                   # noqa: E402
import keypoint_recall as KR                                                # noqa: E402


def load_chapter_segs(mr_path: Path) -> list[list[dict]]:
    d = json.loads(mr_path.read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    idx = {s["segment_id"]: i for i, s in enumerate(segs)}
    out = []
    for ch in (d.get("summary") or {}).get("chapters") or []:
        a, b = ch.get("start_ref"), ch.get("end_ref")
        member = segs[idx[a]: idx[b] + 1] if a in idx and b in idx else \
            [s for s in segs if s["start_ms"] < ch.get("end_ms", 0) and s["end_ms"] > ch.get("start_ms", 0)]
        out.append([s for s in member if (s.get("text") or "").strip()])
    return out


def make_messages(mid_segs, prev_segs, next_segs, bilateral: bool):
    """用生产 _block_summary_messages 造中间章的消息;bilateral 时注入前后章只读参考。"""
    ref_map, _ = _build_compact_ref_map(mid_segs)
    spk_map, _ = _build_compact_speaker_map([s.get("speaker_id", "") for s in mid_segs])
    msgs = _block_summary_messages(mid_segs, None, ref_map=ref_map, speaker_map=spk_map, profile=GENERIC_PROFILE)
    if not bilateral:
        return msgs, ref_map

    def _tl(segs):
        if not segs:
            return "（无）"
        rm, _ = _build_compact_ref_map(segs)
        sm, _ = _build_compact_speaker_map([s.get("speaker_id", "") for s in segs])
        return _render_compact_timeline(segs, rm, sm)

    # 注入双侧参考:呈现前/后章,明确"只读、不摘录、refs只能来自本块"
    prev_tl, next_tl = _tl(prev_segs), _tl(next_segs)
    ref_block = (
        "【参考·前一章（只读，帮助理解衔接，不要摘录其内容，refs 不得来自这里）】\n" + prev_tl + "\n"
        "【参考·后一章（只读，帮助理解衔接，不要摘录其内容，refs 不得来自这里）】\n" + next_tl + "\n\n"
    )
    user = msgs[1]["content"]
    user = ref_block + user  # 参考块置于生产提示词之前
    return [msgs[0], {"role": "user", "content": user}], ref_map


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting-result", required=True, type=Path)
    ap.add_argument("--golden", required=True, type=Path)
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    chaps = load_chapter_segs(args.meeting_result)
    n = len(chaps)
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    session = OllamaSession(OllamaConfig(model=args.model, max_tokens=900), args.out / "_llm")

    def run_arm(bilateral: bool, tag: str):
        summaries, contam_out, contam_tot, chars = [], 0, 0, []
        for i in range(1, n - 1):  # 中间章 i=1..n-2
            mid, prev, nxt = chaps[i], chaps[i - 1], chaps[i + 1]
            msgs, ref_map = make_messages(mid, prev, nxt, bilateral)
            resp = session.request(msgs, args.out / f"{tag}_ch{i}", max_tokens=900, request_kind="a3b")
            raw = parse_content(resp.get("content", "")) or {}
            summ = str(raw.get("summary", "")).strip()
            summaries.append(summ); chars.append(len(summ))
            # 串味:key_refs(compact)映回canonical,看是否落在中间章之外
            mid_ids = {s["segment_id"] for s in mid}
            comp2canon = {v: k for k, v in ref_map.items()}
            for r in (raw.get("key_refs") or []):
                canon = comp2canon.get(str(r), str(r))
                contam_tot += 1
                if canon not in mid_ids:
                    contam_out += 1
        rec = KR.score({"s": summaries}, golden)["recall"]
        return {"arm": tag, "chapters": n - 2, "recall": rec,
                "contam_ref_rate": round(contam_out / contam_tot, 3) if contam_tot else 0.0,
                "avg_chars": round(sum(chars) / max(1, len(chars))), "summaries": summaries}

    a0 = run_arm(False, "A0_single")
    a3b = run_arm(True, "A3b_bilateral")
    for r in (a0, a3b):
        print(f"{r['arm']:16s} 中间章{r['chapters']}  召回={r['recall']}  串味率={r['contam_ref_rate']}  段均字={r['avg_chars']}")

    (args.out / "a3b.json").write_text(json.dumps([a0, a3b], ensure_ascii=False, indent=2), encoding="utf-8")
    L = ["# A3b 双侧上下文 vs A0 单段(项目生产提示词)", "",
         f"- 源:`{args.meeting_result.name}`  中间章 i=1..{n-2}  模型:{args.model}",
         "- 都用 product_summary 生产 block-summary 提示词;A3b 额外注入前后章只读参考。", "",
         "| 臂 | 中间章数 | 关键点召回 | 串味率 | 段均字 |", "|---|---|---|---|---|"]
    for r in (a0, a3b):
        L.append(f"| {r['arm']} | {r['chapters']} | {r['recall']} | {r['contam_ref_rate']} | {r['avg_chars']} |")
    (args.out / "RESULTS_a3b.md").write_text("\n".join(L), encoding="utf-8")
    print(f"\n→ {args.out / 'RESULTS_a3b.md'}")


if __name__ == "__main__":
    main()
