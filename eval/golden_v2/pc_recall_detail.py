"""g1 召回逐条明细:A0章节摘要 + 数字打捞片段 + 每条core_fact命中分析(A0 vs +打捞)。"""
from __future__ import annotations
import json, re, sys, pathlib, math
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT/"src")); sys.path.insert(0, str(ROOT/"eval"/"golden_v2"))
from meeting_agent.llm.ollama_session import OllamaConfig, OllamaSession
from meeting_agent.stages.product_summary import _block_summary_messages, _build_compact_ref_map, _build_compact_speaker_map
from meeting_agent.stages.summary_profiles import GENERIC_PROFILE
from meeting_agent.stages.validation import parse_content
from normalize import norm
_NUM = re.compile(r"[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千万亿]{1,}")

MR = ROOT/"ops/board-results/2026-09-02_003_enrichment-wire-board-verify/g1/harness/meeting_result.json"
GOLD = ROOT/"eval/golden_v2/out/20200707_L_R001S04C01.golden.json"

def salvage(text, win=7):
    out=[]; seen=set()
    for m in _NUM.finditer(text):
        sp=text[max(0,m.start()-win):min(len(text),m.end()+win)].strip()
        if sp not in seen: seen.add(sp); out.append(sp)
    return out

d=json.loads(MR.read_text(encoding="utf-8"))
segs=(d.get("transcript") or {}).get("segments") or []
idx={s["segment_id"]:i for i,s in enumerate(segs)}
chaps=[]
for ch in (d.get("summary") or {}).get("chapters") or []:
    a,b=ch.get("start_ref"),ch.get("end_ref")
    m=segs[idx[a]:idx[b]+1] if a in idx and b in idx else []
    chaps.append([s for s in m if (s.get("text") or "").strip()])
outdir=ROOT/"eval/golden_v2/_pc_detail"
session=OllamaSession(OllamaConfig(model="qwen3:4b",max_tokens=900),outdir); session.out_dir=outdir
summaries=[]; salv=[]
for i,seg in enumerate(chaps):
    rm,_=_build_compact_ref_map(seg); sm,_=_build_compact_speaker_map([s.get("speaker_id","") for s in seg])
    msgs=_block_summary_messages(seg,None,ref_map=rm,speaker_map=sm,profile=GENERIC_PROFILE)
    r=session.request(msgs,outdir/f"ch{i}",max_tokens=900,request_kind="detail")
    summaries.append(str((parse_content(r.get("content",""))or{}).get("summary","")).strip())
    salv+=salvage("".join((s.get("text") or "") for s in seg))
print("=== g1 A0 章节摘要 ===")
for i,s in enumerate(summaries): print(f"[ch{i}] {s}")
print(f"\n=== 数字打捞片段(共{len(set(salv))},样例前25) ===")
print(" | ".join(list(dict.fromkeys(salv))[:25]))
g=json.loads(GOLD.read_text(encoding="utf-8"))
a0=norm(" ".join(summaries)); sv=norm(" ".join(summaries)+" "+" ".join(salv))
print("\n=== 逐条 core_fact 命中 ===")
for cf in g["core_facts"]:
    anch=cf.get("anchors",[]); need=math.ceil(len(anch)/2)
    h0=sum(1 for x in anch if norm(x) in a0); hs=sum(1 for x in anch if norm(x) in sv)
    ok0="命中" if h0>=need else "漏"; oks="命中" if hs>=need else "漏"
    rescued=""
    if ok0=="漏" and oks=="命中":
        for x in anch:
            if norm(x) not in a0:
                snip=next((sp for sp in salv if norm(x) in norm(sp)), "")
                if snip: rescued=f"  <=打捞救回[{x}]于片段: {snip}"; break
    print(f"{cf['id']}[{cf.get('importance')}] A0:{ok0}({h0}/{len(anch)}) +打捞:{oks}({hs}/{len(anch)}) | anchors={anch}{rescued}")
    print(f"     事实: {cf['text']}")
