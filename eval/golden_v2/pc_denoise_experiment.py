"""去噪配对实验:同脚本内 A0臂 vs 集成臂(must_cover+key_data),temp=0.3 各采样 K 次取均值,
判断数字打捞是否真提召回(消掉 4B run 间噪声)。product 是 temp0,方向可迁移。"""
from __future__ import annotations
import json, sys, pathlib, statistics
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT/"src")); sys.path.insert(0, str(ROOT/"eval"/"golden_v2"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession
from meeting_agent.stages.product_summary import (
    _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map, _extract_key_data)
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE
from meeting_agent.stages.validation import parse_content
import score_candidate as SC

BR = ROOT/"ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
CASES = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]
K = 4

def chapters(mr):
    d=json.loads(pathlib.Path(mr).read_text(encoding="utf-8"))
    segs=(d.get("transcript") or {}).get("segments") or []; idx={s["segment_id"]:i for i,s in enumerate(segs)}
    out=[]
    for ch in (d.get("summary") or {}).get("chapters") or []:
        a,b=ch.get("start_ref"),ch.get("end_ref")
        out.append([s for s in segs[idx[a]:idx[b]+1] if (s.get("text") or "").strip()] if a in idx and b in idx else [])
    return out

def gen(chaps, sess, use_kd, tag):
    sums, kdall=[], []
    for i,seg in enumerate(chaps):
        kd=_extract_key_data(seg) if use_kd else None
        if use_kd: kdall+=kd
        rm,_=_build_compact_ref_map(seg); sm,_=_build_compact_speaker_map([s.get("speaker_id","") for s in seg])
        r=sess.request(_block_summary_messages(seg,None,ref_map=rm,speaker_map=sm,profile=GENERIC_PROFILE,key_data=kd),
                       sess.out_dir/tag, max_tokens=1000, request_kind="dn")
        sums.append(str((parse_content(r.get("content",""))or{}).get("summary","")).strip())
    return " ".join(sums), " ".join(sums)+" "+" ".join(kdall)

for g,mid in CASES:
    chaps=chapters(BR/g/"harness/meeting_result.json")
    G=json.loads((ROOT/"eval/golden_v2/out"/f"{mid}.golden.json").read_text(encoding="utf-8"))
    outdir=ROOT/"eval/golden_v2/_pc_dn"/g
    sess=OllamaSession(OllamaConfig(model="qwen3:4b",max_tokens=1000,temperature=0.3),outdir); sess.out_dir=outdir
    a0,ints,intk=[],[],[]
    for r in range(K):
        s_a0,_=gen(chaps,sess,False,f"a0_r{r}")
        s_i,s_ik=gen(chaps,sess,True,f"int_r{r}")
        a0.append(SC.score(G,SC.norm(s_a0))["core_fact_recall"])
        ints.append(SC.score(G,SC.norm(s_i))["core_fact_recall"])
        intk.append(SC.score(G,SC.norm(s_ik))["core_fact_recall"])
        print(f"  {g} run{r}: A0={a0[-1]} INT={ints[-1]} INT+kd={intk[-1]}", flush=True)
    m=lambda x: round(statistics.mean(x),3)
    print(f"== {g} 均值(K={K}): A0={m(a0)}  集成summary={m(ints)}  集成+key_data={m(intk)}  |  Δ(+kd vs A0)={round(m(intk)-m(a0),3)}", flush=True)
