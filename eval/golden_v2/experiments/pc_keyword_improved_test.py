"""改良版关键词(新提示词+去重并集+索引) vs 旧版,在 g1/g2/g3 测覆盖率 + 索引命中率。"""
from __future__ import annotations
import json, sys, pathlib
import jieba, jieba.posseg as pseg
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT/"src")); sys.path.insert(0, str(ROOT/"eval"/"golden_v2"))
from meeting_agent.stages.enrichment import _is_role_or_dept, _KEYWORDS_SCHEMA
from meeting_agent.stages.validation import parse_content
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession
from normalize import norm

BR = ROOT/"ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
CASES = [("g1","学校","20200707_L_R001S04C01"),("g2","化妆品","20200708_L_R002S05C01"),("g3","学校S03","20200707_L_R001S03C01")]
GEN = set("问题 情况 方面 工作 内容 时候 东西 方式 进行 相关 主要 部分 方案 活动 处理 安排 计划 策略 现状 反馈 状况".split())

OLD_SYS = ("你是会议关键词提炼器。从会议内容中提炼最能代表【讨论议题/主题】的关键词(名词/名词短语),覆盖讨论到的主要方面。\n"
           "只要'讨论的事项',不要'谁在讨论'——不要人名、职务称谓、部门/机构名称、说话人标签(如 某某主任/XX部)。\n"
           "只输出词,不要解释。以JSON输出 {\"keywords\":[...]}。")
NEW_SYS = ("你是会议议题标注器。列出本段讨论到的【每一个议题/主题】,含次要话题,不要遗漏。\n"
           "- 每个议题给一个 2~8 字的话题词(名词短语);覆盖全,宁多勿漏,10~20 个;\n"
           "- 只标'讨论的事项',不要人名/职务/部门/说话人标签(如 某主任 / XX部 一律不要);\n"
           "- 只依据本段内容,不编造。只输出 JSON:{\"keywords\":[...]}。")

import re as _re
def safe_keywords(content):
    try:
        return (parse_content(content) or {}).get("keywords") or []
    except Exception:
        m = _re.search(r'"keywords"\s*:\s*\[(.*)', content, _re.S)
        return _re.findall(r'"([^"]+)"', m.group(1)) if m else []

def toks(s):
    return [w for w,f in pseg.cut(s) if f[0] in ("n","v","a") and len(w)>=2 and w not in GEN]

def run_kw(segs, sysprompt, sess, agg, top_k, mt):
    text = "".join((s.get("text") or "") for s in segs)
    freq, order = {}, []
    for i in range(0, len(text), 6000):
        r = sess.request([{"role":"system","content":sysprompt},{"role":"user","content":"会议内容:\n"+text[i:i+6000]}],
                         sess.out_dir/f"b{i}", max_tokens=mt, request_kind="kw")
        for kw in safe_keywords(r.get("content","")):
            w=str(kw).strip()
            if w and not _is_role_or_dept(w):
                if w not in freq: order.append(w)
                freq[w]=freq.get(w,0)+1
    if agg=="freq": ranked=sorted(order,key=lambda w:-freq[w])
    else: ranked=sorted(order,key=lambda w:(-freq[w],order.index(w)))
    return ranked[:top_k]

def coverage(kws, G):
    kt=norm(" ".join(kws))
    ch=[c for c in G["fine_chapters"] if not any(norm(t) in kt for t in toks(c.get("title","")+c.get("topic","")))]
    cf=[cf["id"] for cf in G["core_facts"] if not any(norm(t) in kt for t in toks(cf["text"]))]
    return len(G["fine_chapters"])-len(ch), len(G["fine_chapters"]), len(G["core_facts"])-len(cf), len(G["core_facts"])

def index_hit(kws, segs):
    hit=0
    for kw in kws:
        tk=[t for t in jieba.lcut(kw) if len(t)>=2 and not _is_role_or_dept(t)]
        if any(t in (s.get("text") or "") for t in tk for s in segs): hit+=1
    return hit

for g,name,mid in CASES:
    d=json.loads((BR/g/"harness/meeting_result.json").read_text(encoding="utf-8"))
    segs=(d.get("transcript") or {}).get("segments") or []
    G=json.loads((ROOT/"eval/golden_v2/out"/f"{mid}.golden.json").read_text(encoding="utf-8"))
    outdir=ROOT/"eval/golden_v2/_pc_kwtest"/g; sess=OllamaSession(OllamaConfig(model="qwen3:4b",max_tokens=500),outdir); sess.out_dir=outdir
    old=run_kw(segs,OLD_SYS,sess,"freq",18,300)
    new=run_kw(segs,NEW_SYS,sess,"union",20,500)
    oc=coverage(old,G); nc=coverage(new,G)
    ih=index_hit(new,segs)
    print(f"\n== {g} ({name}) ==")
    print(f"  旧版: {len(old)}词  章节覆盖 {oc[0]}/{oc[1]}  核心事实 {oc[2]}/{oc[3]}")
    print(f"  改良: {len(new)}词  章节覆盖 {nc[0]}/{nc[1]}  核心事实 {nc[2]}/{nc[3]}  | 索引命中 {ih}/{len(new)} (无法定位 {len(new)-ih})")
