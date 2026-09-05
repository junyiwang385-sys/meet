#!/usr/bin/env python3
"""章节摘要「上下文策略」对照实验。

问题：4B 做章节摘要，是【一次一个、互相隔离】好，还是【带上一章上下文】好？
把「批量度」和「上下文度」两个轴拆开，本脚本只动【上下文度】——每臂都对每个章节
产出恰好 1 段摘要，唯一变量是喂不喂上一章、喂多少：

  A0  isolated   仅本章                          （精度上限，无串味风险）
  A1  carryover  本章 + 上一章“本臂产出的一句话摘要”   （现产线做法，轻上下文）
  A2  fullprev   本章 + 上一章“全文原文(只读)”         （重上下文，CLAUDE.md 警告会串味）

章节固定（同一套边界），temperature=0，prompt 骨架逐字一致，只有“上下文块”不同。

三类指标同时看（加上下文的收益 vs 代价）：
  recall           关键点召回（需 --golden）           —— 收益：完整性↑
  anchor_support   refs 落在本章且有效的比例            —— 精度：引用是否靠谱
  contam_ref       refs 指向【本章之外】的比例(仍是有效seg) —— 代价：直接串味信号
  bleed_proxy      Jaccard(摘要,上一章原文) − Jaccard(摘要,本章原文) —— 代价：内容串味代理
  avg_chars        摘要平均字数

用法（先启动 Ollama）：
  set PYTHONIOENCODING=utf-8
  python eval/context_experiment.py ^
    --meeting-result ops/board-results/2026-09-02_003_enrichment-wire-board-verify/g1/harness/meeting_result.json ^
    --arms A0,A1,A2 --model qwen3:4b --out eval/reports/ctx_exp_g1

板端 meeting_result.json 结构：transcript.segments[] + summary.chapters[]（start_ref/end_ref 界定成员）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession  # noqa: E402

sys.path.insert(0, str(ROOT / "eval" / "summary"))
import keypoint_recall  # noqa: E402


# ---------- 数据装载：把 segment 按章节分组 ----------

def load_chapters(meeting_result_path: Path) -> tuple[list[dict], list[dict]]:
    d = json.loads(meeting_result_path.read_text(encoding="utf-8"))
    segments = (d.get("transcript") or {}).get("segments") or []
    chapters = (d.get("summary") or {}).get("chapters") or []
    by_id = {s["segment_id"]: s for s in segments}
    idx_of = {s["segment_id"]: i for i, s in enumerate(segments)}

    grouped: list[dict] = []
    for ci, ch in enumerate(chapters):
        start_ref, end_ref = ch.get("start_ref"), ch.get("end_ref")
        if start_ref in idx_of and end_ref in idx_of:
            lo, hi = idx_of[start_ref], idx_of[end_ref]
            member = segments[lo : hi + 1]
        else:  # 兜底：按时间范围
            s0, s1 = ch.get("start_ms", 0), ch.get("end_ms", 0)
            member = [s for s in segments if s["start_ms"] < s1 and s["end_ms"] > s0]
        member = [s for s in member if (s.get("text") or "").strip()]
        grouped.append(
            {
                "chapter_index": ci,
                "title": ch.get("title", f"章节{ci+1}"),
                "segments": member,
                "segment_ids": {s["segment_id"] for s in member},
            }
        )
    return grouped, segments


def render_timeline(segs: list[dict]) -> str:
    return "\n".join(
        f"{s['segment_id']} [{s.get('speaker_id','?')}] {(s.get('text') or '').strip()}"
        for s in segs
    )


# ---------- 提示词：共享骨架 + 每臂上下文块 ----------

SYSTEM = "你是严谨的会议纪要助手。只输出一个 JSON 对象，不要输出任何多余文字。"

SKELETON = (
    "任务：为【本章】写一段摘要，并给出支撑摘要的原文引用 refs。\n"
    "{context_block}"
    "要求：\n"
    "- summary：80~200 个中文字符，概括本章要点，结论前置，不写流水账。\n"
    "- refs：3~6 个，必须是【本章 Timeline】里出现的 segment_id，指向支撑摘要的原句。\n"
    "- 只依据【本章】内容写摘要；refs 只能来自本章；不要摘录上下文里别章的内容。\n"
    '输出 JSON：{{"summary": "…", "refs": ["seg-xxxxxx", …]}}\n\n'
    "【本章 Timeline】\n{timeline}\n"
)

CTX_A0 = ""
CTX_A1 = "【上一章摘要（仅供理解衔接，不要摘录其内容）】\n{prev_summary}\n\n"
CTX_A2 = "【上一章原文（仅供理解衔接，不要摘录其内容）】\n{prev_timeline}\n\n"
# A1b：强定位——把上一章摘要的用途说成“去重锚点”，正向指令(写增量/写差异)而非消极禁令
CTX_A1B = (
    "【已写过的上一章摘要——用途：去重锚点】\n{prev_summary}\n"
    "说明：上面是上一章已经写好的内容。本章摘要**不得与它重复**；"
    "若本章在延续同一话题，只写本章**新出现的进展、细节或结论**，不要复述上一章已说过的。\n\n"
)

# A2b：全文上一章，但用强结构标记 + 明确白名单区间（测“脚手架能否救回全文上下文”）
SKELETON_A2B = (
    "下面分【参考区】和【本章区】两部分，请严格区分。\n\n"
    "====== 参考区·上一章（只读，仅帮助你理解上下文衔接） ======\n"
    "（以下每行的 segment_id 属于上一章，**严禁**出现在你的 refs 里）\n{prev_timeline}\n\n"
    "====== 本章区·待摘要（你只总结这一部分） ======\n{timeline}\n\n"
    "任务：只为【本章区】写一段摘要，并给出支撑摘要的原文引用 refs。\n"
    "要求：\n"
    "- summary：80~200 个中文字符，只概括【本章区】要点，结论前置；不得写入参考区的内容。\n"
    "- refs：3~6 个，**只能从【本章区】的 segment_id 里选**，范围是 {id_lo} 到 {id_hi}（含）。\n"
    "- 参考区的任何 segment_id 都不允许出现在 refs 里。\n"
    '输出 JSON：{{"summary": "…", "refs": ["seg-xxxxxx", …]}}\n'
)


def build_messages(arm: str, chapter: dict, prev_chapter: dict | None, prev_summary: str) -> list[dict]:
    timeline = render_timeline(chapter["segments"])
    if arm == "A2b" and prev_chapter is not None:
        ids = [s["segment_id"] for s in chapter["segments"]]
        user = SKELETON_A2B.format(
            prev_timeline=render_timeline(prev_chapter["segments"]),
            timeline=timeline, id_lo=ids[0], id_hi=ids[-1],
        )
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    if arm in ("A0", "A2b") or prev_chapter is None:
        ctx = ""
    elif arm == "A1":
        ctx = CTX_A1.format(prev_summary=prev_summary or "（上一章无摘要）")
    elif arm == "A1b":
        ctx = CTX_A1B.format(prev_summary=prev_summary or "（上一章无摘要）")
    elif arm == "A2":
        ctx = CTX_A2.format(prev_timeline=render_timeline(prev_chapter["segments"]))
    else:
        raise ValueError(f"未知臂 {arm}")
    user = SKELETON.format(context_block=ctx, timeline=timeline)
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


# ---------- 容错 JSON 解析 ----------

def loads_tolerant(text: str) -> dict:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


# ---------- 串味代理：字符 3-gram Jaccard ----------

def ngrams(text: str, n: int = 3) -> set[str]:
    t = re.sub(r"\s", "", keypoint_recall.normalize(text))
    return {t[i : i + n] for i in range(max(0, len(t) - n + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------- 主流程 ----------

def run_arm(arm: str, chapters: list[dict], session: OllamaSession, out_dir: Path) -> dict:
    per_chapter = []
    prev_summary = ""
    for i, ch in enumerate(chapters):
        prev_ch = chapters[i - 1] if i > 0 else None
        messages = build_messages(arm, ch, prev_ch, prev_summary)
        req_dir = out_dir / arm / f"ch{i:02d}"
        try:
            resp = session.request(
                messages, req_dir, max_tokens=512,
                request_kind="ctx-exp", request_id=f"{arm}-ch{i:02d}",
            )
            parsed = loads_tolerant(resp.get("content", ""))
        except Exception as exc:  # noqa: BLE001
            parsed = {"_error": repr(exc)}
        summary = str(parsed.get("summary", "")).strip()
        refs = [str(r) for r in parsed.get("refs", []) if isinstance(parsed.get("refs"), list)]
        prev_summary = summary  # 传给下一章（A1 用）

        cur_ids = ch["segment_ids"]
        refs_in = [r for r in refs if r in cur_ids]
        # 有效但落在本章外的 ref（串味）：需要一张全局 id 表判断“有效”，这里用“非本章即算外”
        refs_out = [r for r in refs if r not in cur_ids]
        cur_text = " ".join(s.get("text", "") for s in ch["segments"])
        prev_text = " ".join(s.get("text", "") for s in prev_ch["segments"]) if prev_ch else ""
        bleed = jaccard(ngrams(summary), ngrams(prev_text)) - jaccard(ngrams(summary), ngrams(cur_text)) if prev_ch else 0.0

        per_chapter.append(
            {
                "chapter_index": i, "title": ch["title"],
                "summary": summary, "refs": refs,
                "refs_in": len(refs_in), "refs_out": len(refs_out), "refs_total": len(refs),
                "summary_chars": len(summary), "bleed_delta": round(bleed, 4),
            }
        )

    n_refs = sum(c["refs_total"] for c in per_chapter) or 1
    return {
        "arm": arm,
        "chapters": len(per_chapter),
        "avg_summary_chars": round(sum(c["summary_chars"] for c in per_chapter) / max(1, len(per_chapter)), 1),
        "anchor_support_rate": round(sum(c["refs_in"] for c in per_chapter) / n_refs, 3),
        "contam_ref_rate": round(sum(c["refs_out"] for c in per_chapter) / n_refs, 3),
        "avg_bleed_delta": round(sum(c["bleed_delta"] for c in per_chapter) / max(1, len(per_chapter)), 4),
        "per_chapter": per_chapter,
    }


def compute_recall(arm_result: dict, golden_path: Path | None) -> float | None:
    if not golden_path:
        return None
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    minutes = {"chapters": [{"title": c["title"], "overview": c["summary"]} for c in arm_result["per_chapter"]]}
    return keypoint_recall.score(minutes, golden)["recall"]


def main() -> None:
    ap = argparse.ArgumentParser(description="章节摘要上下文策略对照实验")
    ap.add_argument("--meeting-result", required=True, type=Path)
    ap.add_argument("--golden", type=Path, default=None)
    ap.add_argument("--arms", default="A0,A1,A2")
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    chapters, _ = load_chapters(args.meeting_result)
    print(f"装载 {len(chapters)} 章（源 {args.meeting_result.name}）")
    args.out.mkdir(parents=True, exist_ok=True)

    session = OllamaSession(OllamaConfig(model=args.model), args.out)
    results = []
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        print(f"--- 运行臂 {arm} ---")
        r = run_arm(arm, chapters, session, args.out)
        r["recall"] = compute_recall(r, args.golden)
        results.append(r)
        print(f"  {arm}: recall={r['recall']} anchor={r['anchor_support_rate']} "
              f"contam={r['contam_ref_rate']} bleed={r['avg_bleed_delta']} chars={r['avg_summary_chars']}")

    (args.out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # 对照表
    lines = ["# 章节摘要上下文策略对照", "",
             f"- 源：`{args.meeting_result}`  章节数：{len(chapters)}  模型：{args.model}  temp=0",
             f"- 金标：`{args.golden}`" if args.golden else "- 金标：无（本轮只看 anchor/contam/bleed）", "",
             "| 臂 | 说明 | recall↑ | anchor_support↑ | contam_ref↓ | bleed_delta↓ | avg_chars |",
             "|---|---|---|---|---|---|---|"]
    desc = {"A0": "仅本章(隔离)", "A1": "+上章压缩摘要(现产线)", "A1b": "+上章摘要(强定位/去重)",
            "A2": "+上章全文(重上下文)", "A2b": "+上章全文(强标记白名单)"}
    for r in results:
        lines.append(f"| {r['arm']} | {desc.get(r['arm'],'')} | {r['recall']} | "
                     f"{r['anchor_support_rate']} | {r['contam_ref_rate']} | {r['avg_bleed_delta']} | {r['avg_summary_chars']} |")
    lines += ["", "## 读法",
              "- recall 高 = 完整性好（收益）；contam_ref / bleed_delta 高 = 串味重（代价）。",
              "- 若带上下文臂(A1/A2) recall 仅微升而 contam/bleed 明显↑，则隔离(A0)或轻上下文(A1)更优——印证 CLAUDE.md 原则4。",
              "- bleed_delta 是自动代理，最终串味判定建议再抽样人工核对每臂 2~3 章摘要。"]
    (args.out / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n完成。对照表：{args.out / 'RESULTS.md'}")


if __name__ == "__main__":
    main()
