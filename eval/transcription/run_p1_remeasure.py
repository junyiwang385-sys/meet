# -*- coding: utf-8 -*-
"""点1 重测(改后):PC fsmn-vad thres 0.6(改前) vs 0.2(改后),g1/g2/g5。
指标:FA(collar0.25) + 信息丢失(>2s实义话语<20%覆盖) + 逐句丢率(≥4字&>2s<20%)。"""
import sys, io, pathlib, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT=pathlib.Path(r"C:/Users/Admin/meet"); sys.path[:0]=[str(ROOT/"eval"/"transcription"),str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh
MEET=[("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]; FR=0.01
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
print(f"{'场':>4}{'thres':>7}{'FA(collar)':>12}{'信息丢失(>2s<20%)':>20}{'逐句丢率(≥4字)':>16}")
for tag,mid in MEET:
    au,sr=sf.read(rf"E:/train_L/wav/{mid}.flac",dtype="float32"); mono=au.mean(axis=1) if au.ndim==2 else au
    dur=len(mono)/sr; nfr=int(dur/FR)+1
    segs=[s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if normalize_zh(s.get("text",""))]
    ref=np.zeros(nfr,bool)
    for s in segs:
        a=int(s["start_ms"]/1000/FR); b=min(nfr,int(s["end_ms"]/1000/FR)+1); ref[a:b]=True
    c=int(0.25/FR); bnd=np.zeros(nfr,bool)
    for idx in np.where(np.diff(ref.astype(int))!=0)[0]: bnd[max(0,idx-c):idx+c+1]=True
    mask=~bnd
    sub2=[(s["start_ms"]/1000,s["end_ms"]/1000) for s in segs if (s["end_ms"]-s["start_ms"])/1000>2]
    real4=[(s["start_ms"]/1000,s["end_ms"]/1000) for s in segs if len(normalize_zh(s["text"]))>=4 and (s["end_ms"]-s["start_ms"])/1000>2]
    tmp=pathlib.Path(tempfile.gettempdir())/"p1.wav"; sf.write(str(tmp),mono,sr,subtype="PCM_16")
    for thres in [0.6,0.2]:
        v=vad.generate(input=str(tmp),speech_noise_thres=thres,max_end_silence_time=800)[0]["value"]
        U=unionsegs([(a/1000,b/1000) for a,b in v])
        sysb=np.zeros(nfr,bool)
        for a,b in U:
            sysb[int(a/FR):min(nfr,int(b/FR)+1)]=True
        fa=int((~ref & sysb & mask).sum())/max(1,int((~ref & mask).sum()))
        info=np.mean([cov(a,b,U)<0.2 for a,b in sub2])
        drop4=np.mean([cov(a,b,U)<0.2 for a,b in real4])
        tag2=tag if thres==0.6 else ""
        print(f"{tag2:>4}{thres:>7}{fa:>11.1%}{info:>19.1%}{drop4:>15.1%}")
