# -*- coding: utf-8 -*-
"""板端 VAD 阈值最终判决:板端3D-Speaker 默认 vs speech_noise_thres=0.4/0.2 的整句丢率(g1逐句)+检测占比,
并把 0.4 相对默认【新救回】的段喂 ASR 看真内容/杂质。默认rttm取0048,0.4/0.2取0052。"""
import sys, io, re, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path[:0]=[str(ROOT/"eval"/"transcription"),str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh
MID="20200707_L_R001S04C01"; DUR=1862.276

def rttm_from(path, marker):
    cur=None; segs=[]
    for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        m=re.match(r"===RTTM_(\S+)===",ln)
        if m: cur=m.group(1); continue
        if ln.startswith("==="): cur=None; continue
        if cur==marker and ln.startswith("SPEAKER"):
            p=ln.split(); st,du=float(p[3]),float(p[4])
            if du>0: segs.append((st,st+du))
    return segs
def union(segs):
    if not segs: return []
    s=sorted(segs); u=[list(s[0])]
    for a,b in s[1:]:
        if a<=u[-1][1]: u[-1][1]=max(u[-1][1],b)
        else: u.append([a,b])
    return [(a,b) for a,b in u]
def cov(a,b,U):
    t=0.0
    for s,e in U:
        lo,hi=max(a,s),min(b,e)
        if hi>lo:t+=hi-lo
    return t/(b-a) if b>a else 0
def subtract(A,B):
    out=[]
    for a,b in A:
        cur=[(a,b)]
        for s,e in B:
            nxt=[]
            for x,y in cur:
                if e<=x or s>=y: nxt.append((x,y))
                else:
                    if x<s: nxt.append((x,min(s,y)))
                    if e<y: nxt.append((max(e,x),y))
            cur=nxt
        out+=[(x,y) for x,y in cur if y-x>0.05]
    return out

DEF=ROOT/"ops/board-bridge/results/0048_cat_board_3dspk_rttm.out"
THR=ROOT/"ops/board-bridge/results/0052_cat_vad_thr_rttm.out"
U_def=union(rttm_from(DEF,MID))
U_04=union(rttm_from(THR,"thr0.4"))
U_02=union(rttm_from(THR,"thr0.2"))
segs=[s for s in parse_textgrid(rf"E:/train_L/TextGrid/{MID}.TextGrid") if normalize_zh(s.get("text",""))]
real=[(s["start_ms"]/1000,s["end_ms"]/1000) for s in segs if len(normalize_zh(s["text"]))>=4 and (s["end_ms"]-s["start_ms"])/1000>2]

print(f"g1 实义话语(≥4字&>2s)={len(real)}")
for name,U in [("板端默认",U_def),("thr0.4",U_04),("thr0.2",U_02)]:
    drop=sum(1 for a,b in real if cov(a,b,U)<0.2)
    det=sum(b-a for a,b in U)
    print(f"  {name:8}: 整句丢率={drop/len(real):.1%}({drop}/{len(real)})  检测占比={det/DUR:.0%}  段数~并集{len(U)}")

# 0.4 相对默认 新救回段 → ASR
new=subtract(U_04,U_def)
print(f"\n0.4 相对默认 新增检测={sum(b-a for a,b in new):.0f}s;抽最长几段喂 ASR(真内容=值得救):")
import soundfile as sf, torch
from transformers import Qwen3ASRForConditionalGeneration, AutoProcessor
au,sr=sf.read(rf"E:/train_L/wav/{MID}.flac",dtype="float32"); mono=au.mean(axis=1) if au.ndim==2 else au
DEV="cuda" if torch.cuda.is_available() else "cpu"
proc=AutoProcessor.from_pretrained(r"E:/models/Qwen3-ASR-0.6B-hf")
model=Qwen3ASRForConditionalGeneration.from_pretrained(r"E:/models/Qwen3-ASR-0.6B-hf",dtype=torch.float32).to(DEV).eval()
for a,b in sorted(new,key=lambda x:-(x[1]-x[0]))[:10]:
    clip=mono[int(a*sr):int(b*sr)]
    if len(clip)<0.3*sr: continue
    inp=proc.apply_transcription_request(audio=clip,language="Chinese",prompt=None,sampling_rate=16000).to(DEV)
    with torch.no_grad(): g=model.generate(**inp,max_new_tokens=100,do_sample=False)
    t=proc.batch_decode(g[:,inp["input_ids"].shape[1]:],skip_special_tokens=True)[0].strip()
    print(f"  [{a:7.1f}s +{b-a:4.1f}s] {t[:55] if t else '(空)'}")
