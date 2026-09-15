#!/usr/bin/env python3
"""复现 opus judge 的 P0/P1 符合度评测(忠实度 + 决策符合度),不依赖千问/外部 key。

方法学同 eval/reports/对标飞书阿里_符合度.md(三方分离:候选=4B / 金标=fable5+opus5 / 裁判=opus):
  忠实度 = (supported + 0.5·partial) / claims 数
  over_decision = 候选把金标 status=proposal 的项当成决定/待办产出
  missed_decision = 金标 status=decision 未被候选覆盖
  critical = 编造数字/owner/待办(原文无据)

本脚本只**构造 judge 提示词**(逐字时间线 + 金标决策/提议/事实 + 候选纪要),
由 Claude 子agent(opus 档)作裁判返回严格 JSON。用法:
  python eval/judge_conformance.py <clean|board> <mid|board_meeting_result.json> [golden_id] > prompt.txt
"""
from __future__ import annotations
import json
import pathlib
import sys

ROOT = pathlib.Path(r"C:/Users/Admin/meet")


def candidate_text_from(mr: dict) -> str:
    """从 meeting_result(含 summary+enrichment)拼可读候选纪要(给裁判看的产出)。"""
    summary = mr.get("summary") or {}
    enrich = mr.get("enrichment") or {}
    parts: list[str] = []
    ov = summary.get("overview")
    if ov:
        parts.append("【概览】" + (ov.get("text") if isinstance(ov, dict) else str(ov)))
    for ch in summary.get("chapters") or []:
        parts.append(f"【章】{ch.get('title','')}：{ch.get('overview','')}")
    for d in enrich.get("decisions") or []:
        parts.append(f"【决策】{d.get('decision','') if isinstance(d, dict) else d}")
    for a in summary.get("action_items") or []:
        parts.append(f"【待办】{a.get('task','')}（负责人 {a.get('owner') or '—'}）")
    for q in (enrich.get("quotes") or [])[:10]:
        parts.append(f"【金句】{q.get('quote','')}")
    return "\n".join(parts)


def load_clean(mid: str) -> dict:
    od = ROOT / "eval/_pc_clean" / mid
    mr = json.loads((od / "meeting_result.json").read_text(encoding="utf-8"))
    mr["summary"] = json.loads((od / "meeting_summary.json").read_text(encoding="utf-8"))
    ep = od / "enrichment.json"
    mr["enrichment"] = json.loads(ep.read_text(encoding="utf-8")) if ep.exists() else {}
    return mr


def timeline_text(mr: dict) -> str:
    segs = (mr.get("transcript") or {}).get("segments") or []
    lines = []
    for s in segs:
        if not str(s.get("text") or "").strip():
            continue
        lines.append(f"[{s['segment_id']}][{s.get('speaker_id','')}] {s['text']}")
    return "\n".join(lines)


def build_judge_prompt(candidate: str, golden: dict, timeline: str) -> str:
    decisions = [d for d in golden.get("decisions") or [] if d.get("status") == "decision"]
    proposals = [d for d in golden.get("decisions") or [] if d.get("status") == "proposal"]
    g = {
        "真实决定(decision)": [{"id": d["id"], "text": d["text"], "owner": d.get("owner")} for d in decisions],
        "提议(proposal,未拍板)": [{"id": d["id"], "text": d["text"]} for d in proposals],
        "行动项": [{"id": a["id"], "text": a["text"], "owner": a.get("owner")} for a in golden.get("action_items") or []],
        "核心事实": [{"id": f["id"], "text": f["text"]} for f in golden.get("core_facts") or []],
    }
    schema = {
        "claims": [{"claim": "候选里的一条陈述", "status": "supported|partial|unsupported|contradiction",
                    "severity": "normal|critical", "reason": "依据逐字时间线的判定理由(可引 seg-id)"}],
        "faithfulness": "（supported+0.5*partial）/claims总数, 保留2位小数",
        "critical_count": "severity=critical 的 claim 数(编造数字/owner/待办)",
        "over_decisions": [{"proposal_id": "被当成决定/待办的金标 proposal id", "reason": "候选如何升格了它"}],
        "missed_decisions": [{"golden_id": "未覆盖的真实 decision id", "golden_text": "…", "reason": "候选为何算漏"}],
        "verdict": "ok|weak|fail",
    }
    return f"""你是独立第三方评审(裁判),只依据【官方逐字时间线】这一唯一事实来源,评判【候选纪要】的质量。
候选由一个小模型(4B)生成;金标由另一模型生成并经第三方核验。三方独立,你只对时间线负责。

评判两件事:

1) 忠实度(faithfulness):把候选纪要拆成一条条 claim,逐条对照逐字时间线判定:
   - supported: 时间线明确支持
   - partial: 部分支持/有出入但不算错
   - unsupported: 时间线找不到支持(可能编造)
   - contradiction: 与时间线矛盾
   编造具体数字/负责人/待办(原文无据)的 claim 标 severity=critical。
   faithfulness = (supported + 0.5*partial) / claim 总数。

2) 决策符合度(对照金标的 decision/proposal 区分):
   - over_decision: 候选把金标里【提议(proposal,未拍板)】当成了决定或待办产出 → 列出该 proposal id。
   - missed_decision: 金标里的【真实决定(decision)】候选完全没覆盖 → 列出该 decision id。
   （这是核心红线:小模型/竞品常把"讨论/建议"写成"决定"。）

verdict: fail(忠实度<0.85 或 critical≥3 或 漏决定过半) / weak / ok,综合给。

【只输出严格 JSON,无解释、无 markdown】,schema:
{json.dumps(schema, ensure_ascii=False, indent=2)}

===== 官方逐字时间线(唯一事实来源) =====
{timeline}

===== 金标(参照,fable5生成+opus5核验) =====
{json.dumps(g, ensure_ascii=False, indent=2)}

===== 候选纪要(被评判对象,4B 产出) =====
{candidate}
"""


def main() -> int:
    mode, ident = sys.argv[1], sys.argv[2]
    if mode == "clean":
        mid = ident
        mr = load_clean(mid)
    else:  # board: 直接给 meeting_result.json 路径
        mr = json.loads(pathlib.Path(ident).read_text(encoding="utf-8"))
        mid = sys.argv[3] if len(sys.argv) > 3 else "board"
    golden_id = sys.argv[3] if mode == "clean" and len(sys.argv) > 3 else (sys.argv[4] if len(sys.argv) > 4 else mid)
    golden = json.loads((ROOT / f"eval/golden_v2/out/{golden_id}.golden.json").read_text(encoding="utf-8"))
    prompt = build_judge_prompt(candidate_text_from(mr), golden, timeline_text(mr))
    sys.stdout.write(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
