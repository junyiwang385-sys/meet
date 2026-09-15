"""维度质量评测：pipeline 输出(summary+enrichment) vs golden_v2 金标，
在 decisions / action_items / speakers / enrichment 上出可信度量。

两个口径(诚实分开)：
  - 内容覆盖：金标该条(决策/待办)的内容是否在纪要**任意处**被提到(半命中,同 core_facts 口径)。
    → 反映"模型是否理解到了这件事"。
  - 结构化捕获：金标该条是否被放进**对应结构化字段**(action_items[].task / enrichment.decisions)。
    → 反映"是否被正确抽取成结构"。两者差=理解到了但没结构化出来(4B 待办/决策抽取弱)。
另报：speaker 覆盖(计数)、enrichment 结构统计 + 金句逐字保真率。

⚠️ 金标为银标(fable5+opus5)、金标与板端 ASR 分段不同源→按**文本**比对(非 seg-id/anchor 对齐)。
用法：python eval/golden_v2/score_dimensions.py   (默认 g1/g2/g3/g5，需先跑 pc_full_minutes)
"""
from __future__ import annotations
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "eval" / "golden_v2"))
from score_candidate import norm, score as core_score  # noqa: E402

import jieba  # noqa: E402
jieba.setLogLevel(60)

# --clean: 干净输入线(timeline 真值转写),n=30,隔离 ASR/分离噪声,测纯摘要/结构化质量。
# 默认: board-noisy 端到端线,n=4(受板端 run 限制)。
CLEAN = "--clean" in sys.argv
_BOARD_CASES = [("g1", "20200707_L_R001S04C01"), ("g2", "20200708_L_R002S05C01"),
                ("g3", "20200707_L_R001S03C01"), ("g5", "20200709_L_R002S04C01")]
BR = ROOT / "ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
if CLEAN:
    _mids = sorted(p.name[: -len(".golden.json")]
                   for p in (ROOT / "eval/golden_v2/out").glob("*.golden.json"))
    CASES = [(m, m) for m in _mids]
else:
    CASES = _BOARD_CASES


def _out_dir(tag):
    return ROOT / (f"eval/_pc_clean/{tag}" if CLEAN else f"eval/_pc_full_minutes/{tag}")


def _transcript_path(tag):
    return (_out_dir(tag) / "meeting_result.json") if CLEAN else (BR / tag / "harness/meeting_result.json")
_STOP = set("的了和与在是我们你们他们这那就都也要会对不没有一个进行以及等还把被让给可以需要")


def toks(s):
    return [w for w in jieba.lcut(norm(str(s or ""))) if len(w) >= 2 and w not in _STOP]


def covered(item_text, cand_text):
    """半命中：item 内容词≥一半出现在 cand_text 里。"""
    tk = toks(item_text)
    if not tk:
        return False
    hit = sum(1 for t in set(tk) if t in cand_text)
    return hit >= math.ceil(len(set(tk)) / 2)


def structured_match(gold_text, cand_texts):
    """结构化捕获：金标该条是否与某个候选结构化条目文本半重叠。"""
    g = set(toks(gold_text))
    if not g:
        return False
    for c in cand_texts:
        cs = set(toks(c))
        if cs and len(g & cs) >= math.ceil(len(g) / 2):
            return True
    return False


def recall(items, key, test):
    tot = 0
    hit = 0
    for it in items:
        t = it.get(key) or it.get("text") or ""
        if not str(t).strip():
            continue
        tot += 1
        if test(t):
            hit += 1
    return hit, tot


def eval_one(tag, mid):
    out = _out_dir(tag)
    summ = json.loads((out / "meeting_summary.json").read_text(encoding="utf-8"))
    enr = json.loads((out / "enrichment.json").read_text(encoding="utf-8")) if (out / "enrichment.json").exists() else {}
    gold = json.loads((ROOT / f"eval/golden_v2/out/{mid}.golden.json").read_text(encoding="utf-8"))
    tr = json.loads(_transcript_path(tag).read_text(encoding="utf-8"))
    trans_norm = norm(" ".join(s.get("text", "") for s in (tr.get("transcript") or {}).get("segments") or []))

    # 候选大文本(所有产出，用于"内容覆盖")
    _ov = summ.get("overview")
    parts = [(_ov.get("text") if isinstance(_ov, dict) else _ov) or ""]
    parts += [f"{c.get('title','')} {c.get('overview','')}" for c in (summ.get("chapters") or [])]
    parts += [s.get("overview", "") for s in (summ.get("speakers") or [])]
    parts += [a.get("task", "") for a in (summ.get("action_items") or [])]
    parts += [str(x) for x in (enr.get("keywords") or [])]
    parts += [f"{q.get('question','')} {q.get('answer','')}" for q in (enr.get("qa") or [])]
    parts += [q.get("quote", "") for q in (enr.get("quotes") or [])]
    parts += [f"{d.get('decision','')} {d.get('problem','')}" for d in (enr.get("decisions") or [])]
    cand_all = norm(" ".join(parts))

    # 候选结构化字段文本
    cand_actions = [a.get("task", "") for a in (summ.get("action_items") or [])]
    cand_decisions = [f"{d.get('decision','')} {d.get('problem','')}" for d in (enr.get("decisions") or [])]

    g_dec = gold.get("decisions") or []
    g_act = gold.get("action_items") or []
    g_spk = gold.get("speakers") or []

    # 内容覆盖(该条内容是否在纪要任意处被提到)
    dc_h, dc_t = recall(g_dec, "text", lambda t: covered(t, cand_all))
    ac_h, ac_t = recall(g_act, "text", lambda t: covered(t, cand_all))

    core = core_score(gold, cand_all)
    # 金句逐字保真：quote 字段是否为转写子串
    quotes = enr.get("quotes") or []
    verb = sum(1 for q in quotes if norm(q.get("quote", "")) and norm(q.get("quote", "")) in trans_norm)

    return {
        "tag": tag, "core_recall": core["core_fact_recall"],
        "dec_cover": (dc_h, dc_t), "dec_out": (len(cand_decisions), dc_t),
        "act_cover": (ac_h, ac_t), "act_out": (len(cand_actions), ac_t),
        "spk_cand": len(summ.get("speakers") or []), "spk_gold": len(g_spk),
        "enr": {k: len(enr.get(k) or []) for k in ("keywords", "qa", "quotes", "decisions")},
        "outline": bool(enr.get("outline_summary")),
        "quote_verbatim": (verb, len(quotes)),
    }


def _r(h, t):
    return f"{h}/{t}={h/t:.2f}" if t else "n/a"


def main():
    print(f"口径: {'干净输入线(timeline真值, n=30)' if CLEAN else 'board-noisy 端到端线(n=4)'}")
    rows = []
    for tag, mid in CASES:
        out = _out_dir(tag) / "meeting_summary.json"
        if not out.exists():
            print(f"[{tag}] 缺 pipeline 输出，跳过(先跑 pc_full_minutes)"); continue
        r = eval_one(tag, mid)
        rows.append(r)
        print(f"[{r['tag']}] core召回={r['core_recall']}  "
              f"决策[覆盖 {_r(*r['dec_cover'])} / 产出 {_r(*r['dec_out'])}]  "
              f"待办[覆盖 {_r(*r['act_cover'])} / 产出 {_r(*r['act_out'])}]  "
              f"发言人 {r['spk_cand']}/{r['spk_gold']}  "
              f"enr={r['enr']} outline={r['outline']} 金句逐字={_r(*r['quote_verbatim'])}")

    if rows:
        n = len(rows)
        def mean(f):
            xs = [f(r) for r in rows if f(r) is not None]
            return sum(xs) / len(xs) if xs else 0.0
        def mrate(key):
            h = sum(r[key][0] for r in rows); t = sum(r[key][1] for r in rows)
            return h / t if t else 0.0
        print("=" * 78)
        print(f"均值(n={n}): core召回={mean(lambda r: r['core_recall']):.2f}  "
              f"决策[覆盖{mrate('dec_cover'):.2f} / 产出{mrate('dec_out'):.2f}]  "
              f"待办[覆盖{mrate('act_cover'):.2f} / 产出{mrate('act_out'):.2f}]  "
              f"金句逐字保真={mrate('quote_verbatim'):.2f}")
        print("解读: 覆盖=该条内容在纪要里被提到(理解到了); 产出=结构化字段产出条数/金标条数;"
              " '覆盖高但产出低'=理解到了却没抽成结构(尤其待办, 印证 4B 抽取弱); 参考为银标、文本比对, 供方向判断。")
        # 供 run_all 聚合:落盘 aggregate + 逐场
        agg = {
            "n": n, "line": "clean" if CLEAN else "board",
            "core_recall": round(mean(lambda r: r["core_recall"]), 3),
            "dec_cover": round(mrate("dec_cover"), 3), "dec_out": round(mrate("dec_out"), 3),
            "act_cover": round(mrate("act_cover"), 3), "act_out": round(mrate("act_out"), 3),
            "quote_verbatim": round(mrate("quote_verbatim"), 3),
        }
        out = ROOT / f"eval/reports/dimensions/results_{agg['line']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"aggregate": agg, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"→ {out}")


if __name__ == "__main__":
    main()
