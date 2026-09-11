# -*- coding: utf-8 -*-
"""点4 重测(板端 before/after):g1 用板端真实 rttm 默认 vs 0.2,同合并切块→Qwen3-ASR→拼整会转写,
与 TextGrid 全文比端到端 CER。量 VAD 修复(0.6→0.2)传导到最终转写省了多少 CER。"""
import sys, io, re, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT=pathlib.Path(r"C:/Users/Admin/meet"); sys.path[:0]=[str(ROOT/"eval"/"transcription"),str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh
from score_asr import cer_counts, rate
MID="20200707_L_R001S04C01"; MERGE_GAP,MAX_SEG,PAD=1.0,30.0,0.2
DEF=ROOT/"ops/board-bridge/results/0048_cat_board_3dspk_rttm.out"
THR=ROOT/"ops/board-bridge/results/0052_cat_vad_thr_rttm.out"

def rttm_from(path,marker):
    cur=None; segs=[]
    for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        m=re.match(r"===RTTM_(\S+)===",ln)
        if m: cur=m.group(1); continue
        if ln.startswith("==="): cur=None; continue
        if cur==marker and ln.startswith("SPEAKER"):
            p=ln.split(); st,du,spk=float(p[3]),float(p[4]),p[7]
            if du>0: segs.append((st,st+du,spk))
    return segs
def merge(segs):
    segs=sorted(segs,key=lambda x:x[0]); out=[]
    for s,e,spk in segs:
        if out and out[-1][2]==spk and s-out[-1][1]<=MERGE_GAP and (e-out[-1][0])<=MAX_SEG: out[-1][1]=e
        else: out.append([s,e,spk])
    return out

segs_ref=[s for s in parse_textgrid(rf"E:/train_L/TextGrid/{MID}.TextGrid") if normalize_zh(s.get("text",""))]
ref_full="".join(normalize_zh(s["text"]) for s in sorted(segs_ref,key=lambda x:x["start_ms"]))
import soundfile as sf, torch
au,sr=sf.read(rf"E:/train_L/wav/{MID}.flac",dtype="float32"); mono=au.mean(axis=1) if au.ndim==2 else au
DEV="cuda" if torch.cuda.is_available() else "cpu"
from transformers import Qwen3ASRForConditionalGeneration, AutoProcessor
proc=AutoProcessor.from_pretrained(r"E:/models/Qwen3-ASR-0.6B-hf")
model=Qwen3ASRForConditionalGeneration.from_pretrained(r"E:/models/Qwen3-ASR-0.6B-hf",dtype=torch.float32).to(DEV).eval()
def asr(clip):
    inp=proc.apply_transcription_request(audio=clip,language="Chinese",prompt=None,sampling_rate=16000).to(DEV)
    with torch.no_grad(): g=model.generate(**inp,max_new_tokens=200,do_sample=False)
    return proc.batch_decode(g[:,inp["input_ids"].shape[1]:],skip_special_tokens=True)[0].strip()

for name, segs in [("板端默认(0.6)", rttm_from(DEF,MID)), ("板端0.2", rttm_from(THR,"thr0.2"))]:
    merged=merge(segs); parts=[]
    for i,(a,b,spk) in enumerate(merged):
        clip=mono[int(max(0,a-PAD)*sr):int(min(len(mono)/sr,b+PAD)*sr)]
        if len(clip)<0.3*sr: continue
        try: parts.append((a,asr(clip)))
        except Exception: pass
        if i%50==0: print(f"  ..{name} {i+1}/{len(merged)}",flush=True)
    hyp="".join(normalize_zh(t) for _,t in sorted(parts,key=lambda x:x[0]))
    cc=cer_counts(ref_full,hyp)
    print(f"{name}: 端到端CER={rate(cc['s'],cc['d'],cc['i'],cc['n'])} (S={cc['s']} D={cc['d']} I={cc['i']} N={cc['n']}) 合并段={len(merged)}",flush=True)
