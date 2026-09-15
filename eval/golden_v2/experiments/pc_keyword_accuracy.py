"""实测 4B 归纳关键词的准确性:忠实度(词是否在转写里)+ 称谓漏网率;对照 jieba 确定性版。"""
from __future__ import annotations
import json, sys, pathlib
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT/"src")); sys.path.insert(0, str(ROOT/"eval"/"golden_v2"))
from meeting_agent.stages.enrichment import extract_keywords, _is_role_or_dept
from meeting_agent.stages.validation import parse_content
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession
from normalize import norm
import jieba.analyse

BR = ROOT/"ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
CASES = [("g1","学校"), ("g2","化妆品")]

def segs_of(g):
    d = json.loads((BR/g/"harness/meeting_result.json").read_text(encoding="utf-8"))
    return (d.get("transcript") or {}).get("segments") or []

def jieba_kw(text, top_k=18):
    cands = jieba.analyse.textrank(text, topK=top_k*3, allowPOS=("n","nz","ns","nt","vn","an"))
    return [w for w in cands if len(w)>=2 and not _is_role_or_dept(w)][:top_k]

def faithful_rate(kws, tx):
    n = norm(tx)
    hit = [k for k in kws if norm(k) in n]
    return len(hit), [k for k in kws if norm(k) not in n]

for g, name in CASES:
    segs = segs_of(g)
    tx = "".join((s.get("text") or "") for s in segs)
    outdir = ROOT/"eval/golden_v2/_pc_kw"/g
    sess = OllamaSession(OllamaConfig(model="qwen3:4b", max_tokens=300), outdir); sess.out_dir = outdir
    def llm_call(messages, schema, max_tokens=300):
        r = sess.request(messages, outdir/"kw", max_tokens=max_tokens, request_kind="kw")
        return parse_content(r.get("content","")) or {}
    kw4b = extract_keywords(segs, llm_call)
    kwj = jieba_kw(tx)
    h4, drift4 = faithful_rate(kw4b, tx)
    hj, driftj = faithful_rate(kwj, tx)
    role4 = [k for k in kw4b if _is_role_or_dept(k)]
    print(f"\n===== {g} ({name}) =====")
    print(f"[4B 关键词] {len(kw4b)}个  忠实度(在转写里)={h4}/{len(kw4b)}={h4/max(1,len(kw4b)):.0%}  称谓漏网={len(role4)}")
    print("  4B:", " | ".join(kw4b))
    if drift4: print("  ↑漂移(转写查无):", " | ".join(drift4))
    print(f"[jieba 关键词] {len(kwj)}个  忠实度={hj}/{len(kwj)}={hj/max(1,len(kwj)):.0%}")
    print("  jieba:", " | ".join(kwj))
    if driftj: print("  ↑查无:", " | ".join(driftj))
