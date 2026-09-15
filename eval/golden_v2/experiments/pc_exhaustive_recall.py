"""原型:穷举抽取式块内提示词(去重要性判断/去封顶/锚词强制),本机 Ollama 跑,对新金标算召回。
用法: python pc_exhaustive_recall.py <board_meeting_result.json> <golden.json>
"""
from __future__ import annotations
import json, sys, pathlib

ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "eval" / "golden_v2"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession  # noqa: E402
import score_candidate as SC  # noqa: E402


def loads_tolerant(t: str) -> dict:
    import json as _j
    try:
        return _j.loads(t)
    except Exception:
        s = t.find("{")
        if s < 0:
            return {}
        depth = 0
        for i in range(s, len(t)):
            if t[i] == "{":
                depth += 1
            elif t[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return _j.loads(t[s:i + 1])
                    except Exception:
                        break
        # 截断兜底:逐字段正则抢救数组
        import re as _re
        out = {}
        for key in ("numbers", "entities", "decisions", "proposals", "todos", "disputes"):
            m = _re.search(key + r'"\s*:\s*\[(.*?)\]', t, _re.S)
            if m:
                out[key] = _re.findall(r'"([^"]+)"', m.group(1))
        ms = _re.search(r'summary"\s*:\s*"(.*?)"\s*[},]', t, _re.S)
        if ms:
            out["summary"] = ms.group(1)
        return out

SYS = "你是会议事实抽取器,只输出一个合法 JSON 对象,不要多余文字。"
USER = (
    "先对下面这段会议内容做【穷举抽取】:只做检索,不判断重不重要,不遗漏、不封顶;再写摘要。\n"
    "输出 JSON:\n"
    "{\n"
    '  "numbers":["本段每一个 数字/金额/日期/时间/次数,原样,不换算不省略"],\n'
    '  "entities":["本段每一个 人名/职务/机构/专有名词/产品名,原样"],\n'
    '  "decisions":["每处 明确要求执行/明确承诺去做 的事(含谁提出/负责)"],\n'
    '  "proposals":["每处 建议/考虑/讨论方向/待定(不要写成决定)"],\n'
    '  "todos":["每处后续动作"],\n'
    '  "disputes":["每处 分歧/否决/待确认"],\n'
    '  "summary":"依据上面各类写连续摘要,结论前置;numbers 与 entities 的每一项都必须原样出现在 summary 里,不得改写或省略;proposals 用建议/考虑表述,严禁写成决定"\n'
    "}\n"
    "只依据本段内容,某类没有就给 []。/no_think\n\n会议内容:\n{block}"
)


def chapters(mr):
    d = json.loads(pathlib.Path(mr).read_text(encoding="utf-8"))
    segs = (d.get("transcript") or {}).get("segments") or []
    idx = {s["segment_id"]: i for i, s in enumerate(segs)}
    out = []
    for ch in (d.get("summary") or {}).get("chapters") or []:
        a, b = ch.get("start_ref"), ch.get("end_ref")
        m = segs[idx[a]:idx[b] + 1] if a in idx and b in idx else []
        out.append("".join((s.get("text") or "").strip() for s in m if (s.get("text") or "").strip()))
    return out


def main():
    mr, gold = sys.argv[1], sys.argv[2]
    chaps = chapters(mr)
    outdir = ROOT / "eval" / "golden_v2" / "_pc_exh"
    session = OllamaSession(OllamaConfig(model="qwen3:4b", max_tokens=2200), outdir)
    session.out_dir = outdir
    summ_only, facts_all = [], []
    for i, block in enumerate(chaps):
        msgs = [{"role": "system", "content": SYS},
                {"role": "user", "content": USER.replace("{block}", block)}]
        r = session.request(msgs, outdir / f"ch{i}", max_tokens=2200, request_kind="exh")
        raw = loads_tolerant(r.get("content", "")) or {}
        summ_only.append(str(raw.get("summary", "")).strip())
        bag = []
        for k in ("numbers", "entities", "decisions", "proposals", "todos", "disputes"):
            v = raw.get(k) or []
            if isinstance(v, list):
                bag += [str(x) for x in v]
        facts_all.append(" ".join(bag) + " " + str(raw.get("summary", "")))
        print(f"  ch{i} done", flush=True)
    g = json.loads(pathlib.Path(gold).read_text(encoding="utf-8"))
    r_summ = SC.score(g, SC.norm(" ".join(summ_only)))
    r_full = SC.score(g, SC.norm(" ".join(facts_all)))
    print("穷举版 g1  仅summary召回=%s(%d/%d) 低频=%s  |  抽取+summary召回=%s(%d/%d) 低频=%s" % (
        r_summ["core_fact_recall"], r_summ["recalled"], r_summ["total"], r_summ["lowfreq"],
        r_full["core_fact_recall"], r_full["recalled"], r_full["total"], r_full["lowfreq"]))
    print("仍漏(抽取+summary):", [(m["id"], m["text"][:18]) for m in r_full["missed"]])


if __name__ == "__main__":
    main()
