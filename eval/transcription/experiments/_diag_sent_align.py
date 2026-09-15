# -*- coding: utf-8 -*-
"""逐句对齐:TextGrid 每条【有文字】的话语 vs 板端3D-Speaker rttm 语音并集覆盖。
判"整句被丢"(覆盖<20% 且有实义文字 且>2s)→ 把原文/时间调出来人工看是真丢还是可解释。
用 board 语音【并集】(任意说话人)算覆盖:所以重叠句只要那段有任何语音就算覆盖,
<20% 覆盖=板端那段【压根没检测到任何语音】=真漏,不是归属错。"""
import sys, io, re, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path[:0] = [str(ROOT/"eval"/"transcription"), str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh
BR = ROOT/"ops/board-bridge/results/0048_cat_board_3dspk_rttm.out"

def board_union(mid):
    cur=None; segs=[]
    for ln in BR.read_text(encoding="utf-8").splitlines():
        m=re.match(r"===RTTM_(\S+)===",ln)
        if m: cur=m.group(1); continue
        if ln.startswith("==="): cur=None; continue
        if cur==mid and ln.startswith("SPEAKER"):
            p=ln.split(); st,du=float(p[3]),float(p[4])
            if du>0: segs.append((st,st+du))
    segs.sort(); u=[]
    for a,b in segs:
        if u and a<=u[-1][1]: u[-1][1]=max(u[-1][1],b)
        else: u.append([a,b])
    return u

def cov(a,b,union):
    tot=0.0
    for s,e in union:
        lo,hi=max(a,s),min(b,e)
        if hi>lo: tot+=hi-lo
    return tot/(b-a) if b>a else 0.0

for tag,mid in [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]:
    U=board_union(mid)
    segs=[s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if normalize_zh(s.get("text",""))]
    real=[s for s in segs if len(normalize_zh(s["text"]))>=4 and (s["end_ms"]-s["start_ms"])/1000>2]
    dropped=[]
    for s in real:
        a,b=s["start_ms"]/1000,s["end_ms"]/1000
        c=cov(a,b,U)
        if c<0.2: dropped.append((a,b-a,c,s["speaker_id"],normalize_zh(s["text"])))
    print(f"\n==== {tag} 实义话语(≥4字&>2s)共{len(real)}条,整句丢(<20%覆盖)={len(dropped)}条 ({len(dropped)/len(real):.0%}) ====")
    for a,d,c,spk,txt in sorted(dropped, key=lambda x:-x[1])[:12]:
        print(f"  [{a:7.1f}s +{d:4.1f}s cov={c:.0%} {spk}] {txt[:40]}")
