# -*- coding: utf-8 -*-
"""全30场 VAD 泛化验证(收口):PC fsmn-vad thres 0.6 vs 0.2,逐句丢率(≥4字&>2s<20%)+FA(collar0.25)。
目的:确认在没参与调参的会上 0.2 也把丢率压下去、且 FA 不失控(尤其 g2 型真静音多的会)。"""
import sys, io, glob, pathlib, tempfile, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT=pathlib.Path(r"C:/Users/Admin/meet"); sys.path[:0]=[str(ROOT/"eval"/"transcription"),str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh
OUT=ROOT/"eval/transcription/_out/p1_full30.txt"; FR=0.01
DEV3={"20200707_L_R001S04C01","20200708_L_R002S05C01","20200709_L_R002S04C01"}  # 调参用过的3场
import numpy as np, soundfile as sf
from funasr import AutoModel
vad=AutoModel(model="fsmn-vad",disable_update=True)
def unionsegs(segs):
    if not segs: return []
    s=sorted(segs); u=[list(s[0])]
    for a,b in s[1:]:
        if a<=u[-1][1]: u[-1][1]=max(u[-1][1],b)
        else: u.append([a,b])
    return [(a,b) for a,b in u]
def cov(a,b,U):
    t=0
    for s,e in U:
        lo,hi=max(a,s),min(b,e)
        if hi>lo:t+=hi-lo
    return t/(b-a) if b>a else 0

log=open(OUT,"w",encoding="utf-8")
def w(*a): s=" ".join(str(x) for x in a); print(s,flush=True); log.write(s+"\n"); log.flush()
mids=[pathlib.Path(p).stem for p in sorted(glob.glob(r"E:/train_L/TextGrid/*.TextGrid"))]
w(f"全 {len(mids)} 场;* = 调参用过的dev场。逐句丢率(越低越好)/ FA(collar)")
w(f"{'会':<28}{'丢率0.6':>9}{'丢率0.2':>9}{'FA0.6':>8}{'FA0.2':>8}")
rows=[]
for mid in mids:
    flac=rf"E:/train_L/wav/{mid}.flac"
    if not pathlib.Path(flac).exists(): continue
    au,sr=sf.read(flac,dtype="float32"); mono=au.mean(axis=1) if au.ndim==2 else au
    dur=len(mono)/sr; nfr=int(dur/FR)+1
    segs=[s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if normalize_zh(s.get("text",""))]
    ref=np.zeros(nfr,bool)
    for s in segs:
        ref[int(s["start_ms"]/1000/FR):min(nfr,int(s["end_ms"]/1000/FR)+1)]=True
    c=int(0.25/FR); bnd=np.zeros(nfr,bool)
    for idx in np.where(np.diff(ref.astype(int))!=0)[0]: bnd[max(0,idx-c):idx+c+1]=True
    mask=~bnd; refns=max(1,int((~ref&mask).sum()))
    real4=[(s["start_ms"]/1000,s["end_ms"]/1000) for s in segs if len(normalize_zh(s["text"]))>=4 and (s["end_ms"]-s["start_ms"])/1000>2]
    if not real4: continue
    tmp=pathlib.Path(tempfile.gettempdir())/"pf.wav"; sf.write(str(tmp),mono,sr,subtype="PCM_16")
    r={}
    for thres in [0.6,0.2]:
        v=vad.generate(input=str(tmp),speech_noise_thres=thres,max_end_silence_time=800)[0]["value"]
        U=unionsegs([(a/1000,b/1000) for a,b in v])
        sysb=np.zeros(nfr,bool)
        for a,b in U: sysb[int(a/FR):min(nfr,int(b/FR)+1)]=True
        r[thres]=(np.mean([cov(a,b,U)<0.2 for a,b in real4]), int((~ref&sysb&mask).sum())/refns)
    star="*" if mid in DEV3 else " "
    w(f"{star}{mid:<27}{r[0.6][0]:>8.1%}{r[0.2][0]:>8.1%}{r[0.6][1]:>7.1%}{r[0.2][1]:>7.1%}")
    rows.append((mid,r[0.6][0],r[0.2][0],r[0.6][1],r[0.2][1]))

d06=[x[1] for x in rows]; d02=[x[2] for x in rows]; fa06=[x[3] for x in rows]; fa02=[x[4] for x in rows]
w("\n================ 全30 汇总 ================")
w(f"逐句丢率 均值: 0.6={statistics.mean(d06):.1%} → 0.2={statistics.mean(d02):.1%}  (中位 {statistics.median(d06):.1%}→{statistics.median(d02):.1%})")
w(f"FA 均值:      0.6={statistics.mean(fa06):.1%} → 0.2={statistics.mean(fa02):.1%}  (中位 {statistics.median(fa06):.1%}→{statistics.median(fa02):.1%})")
w(f"0.2 后丢率仍>10% 的会: {sum(1 for x in d02 if x>0.1)}/{len(rows)}")
w(f"0.2 后 FA>25%(疑似过火)的会: {sum(1 for x in fa02 if x>0.25)}/{len(rows)}")
worst=sorted(rows,key=lambda x:-x[4])[:5]
w("FA 最高5场(0.2)——过火风险:")
for mid,_,_,f6,f2 in worst: w(f"  {mid}: FA {f6:.1%}→{f2:.1%}")
log.close()
