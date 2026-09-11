# -*- coding: utf-8 -*-
"""VAD 参数调优测试矩阵:扫 fsmn-vad 的 speech_noise_thres × max_end_silence_time(× pad 后处理 × 通道),
用逐句 harness 量【整句丢率】(cov<20% 且 ≥4字&>2s 的实义话语),配检测语音占比(过火代理)。
目标:找压漏检的拐点。PC 上跑(fsmn-vad 快);board 3D-Speaker 覆盖比PC更严(43%vs54%),
故绝对丢率PC偏低,但参数方向/相对增益可迁移,最终board复验。"""
from __future__ import annotations
import sys, io, pathlib, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path[:0] = [str(ROOT/"eval"/"transcription"), str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh

MEET = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]
OUT = ROOT/"eval/transcription/_out/vad_sweep.txt"
THRES = [0.6, 0.4, 0.2, 0.0, -0.2]
ENDSIL = [800, 1500, 2500]
PADS = [0.0, 0.25]

def union(segs):
    if not segs: return []
    s=sorted(segs); u=[list(s[0])]
    for a,b in s[1:]:
        if a<=u[-1][1]: u[-1][1]=max(u[-1][1],b)
        else: u.append([a,b])
    return u
def cov(a,b,U):
    t=0.0
    for s,e in U:
        lo,hi=max(a,s),min(b,e)
        if hi>lo: t+=hi-lo
    return t/(b-a) if b>a else 0.0

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    log=open(OUT,"w",encoding="utf-8")
    def w(*a): s=" ".join(str(x) for x in a); print(s); log.write(s+"\n"); log.flush()
    import numpy as np, soundfile as sf
    from funasr import AutoModel
    vad=AutoModel(model="fsmn-vad", disable_update=True)

    # 预载音频 + 实义句
    data={}
    for tag,mid in MEET:
        au,sr=sf.read(rf"E:/train_L/wav/{mid}.flac",dtype="float32")
        mono=au.mean(axis=1) if au.ndim==2 else au
        ch0=au[:,0] if au.ndim==2 else au
        segs=[s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if normalize_zh(s.get("text",""))]
        real=[(s["start_ms"]/1000,s["end_ms"]/1000) for s in segs
              if len(normalize_zh(s["text"]))>=4 and (s["end_ms"]-s["start_ms"])/1000>2]
        data[mid]=dict(mono=mono,ch0=ch0,sr=sr,real=real,dur=len(mono)/sr)

    def run_vad(sig,sr,thres,endsil):
        tmp=pathlib.Path(tempfile.gettempdir())/"vs.wav"; sf.write(str(tmp),sig,sr,subtype="PCM_16")
        r=vad.generate(input=str(tmp), speech_noise_thres=thres, max_end_silence_time=endsil)
        return [(a/1000,b/1000) for a,b in r[0]["value"]]

    def score(segs, real, dur, pad):
        U=union([(max(0,a-pad),b+pad) for a,b in segs])
        det=sum(b-a for a,b in U)
        drop=sum(1 for a,b in real if cov(a,b,U)<0.2)
        return drop/len(real) if real else 0, det/dur
    def agg(chan, thres, endsil, pad):
        dr=[]; de=[]
        for _,mid in MEET:
            d=data[mid]; segs=run_vad(d[chan],d["sr"],thres,endsil)
            r,e=score(segs,d["real"],d["dur"],pad); dr.append(r); de.append(e)
        return sum(dr)/3, sum(de)/3

    # 缓存 VAD 段(pad 后处理不重跑 VAD)
    w("=== VAD 参数矩阵(mean 通道;丢率=整句<20%覆盖 实义句;检测=语音占比) ===")
    w(f"{'thres':>6}{'endsil':>8}{'pad':>6}{'丢率':>8}{'检测占比':>10}")
    rows=[]
    for thres in THRES:
        for endsil in ENDSIL:
            segs_by_mid={mid:run_vad(data[mid]["mono"],data[mid]["sr"],thres,endsil) for _,mid in MEET}
            for pad in PADS:
                dr=[]; de=[]
                for _,mid in MEET:
                    d=data[mid]; r,e=score(segs_by_mid[mid],d["real"],d["dur"],pad); dr.append(r); de.append(e)
                mdr,mde=sum(dr)/3,sum(de)/3; rows.append((thres,endsil,pad,mdr,mde))
                flag=" ←默认" if (thres==0.6 and endsil==800 and pad==0) else ""
                w(f"{thres:>6}{endsil:>8}{pad:>6}{mdr:>7.1%}{mde:>9.1%}{flag}")
    w("\n=== 前端 ch0 抽查(thres 0.6/0.2, endsil 800, pad 0.25) ===")
    for thres in [0.6,0.2]:
        mdr,mde=agg("ch0",thres,800,0.25)
        w(f"  ch0 thres={thres}: 丢率={mdr:.1%} 检测={mde:.1%}")
    w("\n=== 最优(丢率最低且检测<70%) ===")
    ok=[r for r in rows if r[4]<0.70]
    for r in sorted(ok,key=lambda x:x[3])[:5]:
        w(f"  thres={r[0]} endsil={r[1]} pad={r[2]} → 丢率={r[3]:.1%} 检测={r[4]:.1%}")
    log.close()

if __name__=="__main__":
    main()
