"""集成后重跑:用改过的 product_summary(_block_summary_messages 带 must_cover + _extract_key_data),
真 pipeline 出摘要,对金标算召回。summary-only(must_cover效果) vs summary+key_data(产品实际展示)。"""
from __future__ import annotations
import json, sys, pathlib
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT/"src")); sys.path.insert(0, str(ROOT/"eval"/"golden_v2"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession
from meeting_agent.stages.product_summary import (
    _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map, _extract_key_data)
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE
from meeting_agent.stages.validation import parse_content
import score_candidate as SC

BR = ROOT/"ops/board-results/2026-09-02_003_enrichment-wire-board-verify"
CASES = [("g1","20200707_L_R001S04C01",0.643),("g2","20200708_L_R002S05C01",0.786),
         ("g3","20200707_L_R001S03C01",0.643),("g5","20200709_L_R002S04C01",0.786)]

def chapters(mr):
    d=json.loads(pathlib.Path(mr).read_text(encoding="utf-8"))
    segs=(d.get("transcript") or {}).get("segments") or []
    idx={s["segment_id"]:i for i,s in enumerate(segs)}
    out=[]
    for ch in (d.get("summary") or {}).get("chapters") or []:
        a,b=ch.get("start_ref"),ch.get("end_ref")
        m=segs[idx[a]:idx[b]+1] if a in idx and b in idx else []
        out.append([s for s in m if (s.get("text") or "").strip()])
    return out

for g,mid,a0base in CASES:
    chaps=chapters(BR/g/"harness/meeting_result.json")
    outdir=ROOT/"eval/golden_v2/_pc_integ"/g
    sess=OllamaSession(OllamaConfig(model="qwen3:4b",max_tokens=1000),outdir); sess.out_dir=outdir
    summaries, kd_all = [], []
    for i,seg in enumerate(chaps):
        kd=_extract_key_data(seg)
        rm,_=_build_compact_ref_map(seg); sm,_=_build_compact_speaker_map([s.get("speaker_id","") for s in seg])
        msgs=_block_summary_messages(seg,None,ref_map=rm,speaker_map=sm,profile=GENERIC_PROFILE,key_data=kd)
        r=sess.request(msgs,outdir/f"ch{i}",max_tokens=1000,request_kind="integ")
        summaries.append(str((parse_content(r.get("content",""))or{}).get("summary","")).strip())
        kd_all+=kd
    g_=json.loads((ROOT/"eval/golden_v2/out"/f"{mid}.golden.json").read_text(encoding="utf-8"))
    r_s=SC.score(g_, SC.norm(" ".join(summaries)))
    r_k=SC.score(g_, SC.norm(" ".join(summaries)+" "+" ".join(kd_all)))
    print("%s A0基线=%.3f | 集成summary(must_cover)=%s(%d/%d) | summary+key_data=%s(%d/%d) 低频%s | key_data去重=%d"%(
        g,a0base, r_s["core_fact_recall"],r_s["recalled"],r_s["total"],
        r_k["core_fact_recall"],r_k["recalled"],r_k["total"],r_k["lowfreq"], len(set(kd_all))), flush=True)
