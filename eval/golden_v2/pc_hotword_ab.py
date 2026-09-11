# -*- coding: utf-8 -*-
"""热词增益 A/B(PC, HF Qwen3-ASR-0.6B),n=3 场:同一段远场会议音频,
arm A = 无 system prompt(基线),arm B = system prompt 塞会前专名表(=板端 C++ 改法同机制)。
指标:role专名命中率 + 全热词命中率 + CER + echo误插率(hyp出现但该段参考没说的热词/说话次数)。
只跑含专名的参考区间,CPU 可控。结果写 out 文件(UTF-8)。"""
from __future__ import annotations
import sys, json, pathlib, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path.insert(0, str(ROOT / "eval" / "golden_v2"))
from build_timeline import parse_textgrid

MODEL_DIR = r"E:/models/Qwen3-ASR-0.6B-hf"
MEETINGS = [("g1", "20200707_L_R001S04C01"), ("g2", "20200708_L_R002S05C01"), ("g5", "20200709_L_R002S04C01")]
OUT = ROOT / "eval/golden_v2/_pc_hotword/hotword_ab_n3.txt"
MAX_CLIPS = 40
PAD = 0.2

def levenshtein(a, b):
    if a == b: return 0
    la, lb = len(a), len(b)
    if not la: return lb
    if not lb: return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0]*lb
        for j in range(1, lb + 1):
            cur[j] = min(prev[j]+1, cur[j-1]+1, prev[j-1]+(a[i-1] != b[j-1]))
        prev = cur
    return prev[lb]

def norm(s):
    return re.sub(r"[\s，。、！？：；,.!?:;\"'（）()【】\[\]<>]+", "", s or "")

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    log = open(OUT, "w", encoding="utf-8")
    def w(*a):
        line = " ".join(str(x) for x in a); print(line); log.write(line+"\n"); log.flush()

    w("[模型] 载入", MODEL_DIR, "...")
    import torch
    from transformers import Qwen3ASRForConditionalGeneration, AutoProcessor
    DEV = "cuda" if torch.cuda.is_available() else "cpu"
    DT = torch.float32   # 4060 上 0.6B fp32 已够快,避免 fp16 输入特征 dtype 不匹配
    proc = AutoProcessor.from_pretrained(MODEL_DIR)
    model = Qwen3ASRForConditionalGeneration.from_pretrained(MODEL_DIR, dtype=DT).to(DEV).eval()
    w("[模型] ok  device=%s dtype=%s" % (DEV, DT), "\n")
    import soundfile as sf

    def transcribe(wav, prompt):
        inputs = proc.apply_transcription_request(audio=wav, language="Chinese", prompt=prompt, sampling_rate=16000).to(DEV)
        with torch.no_grad():
            gen = model.generate(**inputs, max_new_tokens=128, do_sample=False)
        return proc.batch_decode(gen[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()

    han = lambda t: bool(re.fullmatch(r"[\u4e00-\u9fff]{2,8}", t or ""))
    agg = {}  # tag -> metrics
    for tag, mid in MEETINGS:
        g = json.loads((ROOT/"eval/golden_v2/out"/f"{mid}.golden.json").read_text(encoding="utf-8"))
        roles = [s.get("role","").strip() for s in g.get("speakers",[]) if len(s.get("role","").strip())>=2]
        roles = list(dict.fromkeys(roles))
        anchors = [a for f in (g.get("core_facts") or []) for a in (f.get("anchors") or [])]
        terms = list(dict.fromkeys(roles + [a for a in anchors if han(a)]))
        hot = "、".join(terms); role_set=set(roles); all_set=set(terms)
        def hit(text, tset): n=norm(text); return [t for t in tset if norm(t) in n]

        segs = [s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if norm(s.get("text"))]
        clips = [s for s in segs if hit(s["text"], all_set)][:MAX_CLIPS]
        audio, sr = sf.read(rf"E:/train_L/wav/{mid}.flac", dtype="float32")
        if audio.ndim == 2: audio = audio.mean(axis=1)
        w(f"==== {tag} {mid}  roles={len(roles)} 热词={len(terms)} 含专名区间={len([s for s in segs if hit(s['text'],all_set)])} 取{len(clips)} 音频{len(audio)/sr:.0f}s ====")

        m = dict(ref_r=0,rA=0,rB=0, ref_t=0,tA=0,tB=0, cAn=0,cAd=0,cBn=0,cBd=0, spk=0,echoA=0,echoB=0)
        ex=[]
        for i,s in enumerate(clips):
            a=max(0,s["start_ms"]/1000-PAD); b=min(len(audio)/sr,s["end_ms"]/1000+PAD)
            clip=audio[int(a*sr):int(b*sr)]
            if len(clip)<0.3*sr: continue
            ref=s["text"]; nref=norm(ref)
            try:
                hA=transcribe(clip,None); hB=transcribe(clip,hot)
            except Exception as e:
                w(f"  [clip {i} ERR]", repr(e)[:150]); continue
            rt=hit(ref,role_set); tt=hit(ref,all_set)
            m["ref_r"]+=len(rt); m["ref_t"]+=len(tt); m["spk"]+=1
            m["rA"]+=sum(norm(t) in norm(hA) for t in rt); m["rB"]+=sum(norm(t) in norm(hB) for t in rt)
            m["tA"]+=sum(norm(t) in norm(hA) for t in tt); m["tB"]+=sum(norm(t) in norm(hB) for t in tt)
            # echo:出现在 hyp 但该段参考没说的热词
            m["echoA"]+=len([t for t in all_set if norm(t) in norm(hA) and norm(t) not in nref])
            m["echoB"]+=len([t for t in all_set if norm(t) in norm(hB) and norm(t) not in nref])
            m["cAn"]+=levenshtein(norm(hA),nref); m["cAd"]+=len(nref)
            m["cBn"]+=levenshtein(norm(hB),nref); m["cBd"]+=len(nref)
            if len(ex)<6 and rt and any(norm(t) not in norm(hA) for t in rt): ex.append((ref,hA,hB,rt))
            if i%10==0: w(f"  ..{tag} clip {i+1}/{len(clips)}")
        agg[tag]=m
        rr=lambda n,d:(round(n/d,3) if d else None)
        w(f"  {tag} role命中 A={rr(m['rA'],m['ref_r'])} B={rr(m['rB'],m['ref_r'])} (n={m['ref_r']}) | 全热词 A={rr(m['tA'],m['ref_t'])} B={rr(m['tB'],m['ref_t'])} (n={m['ref_t']}) | CER A={rr(m['cAn'],m['cAd'])} B={rr(m['cBn'],m['cBd'])} | echo/段 A={rr(m['echoA'],m['spk'])} B={rr(m['echoB'],m['spk'])}")
        for ref,hA,hB,rt in ex:
            w("   REF:",ref); w("   A  :",hA); w("   B  :",hB); w("   role:","、".join(rt)); w("")

    # 汇总(三场合并分母)
    S={k:sum(agg[t][k] for t in agg) for k in agg[next(iter(agg))]}
    rr=lambda n,d:(round(n/d,3) if d else None)
    w("\n================ 三场合并 ================")
    w(f"role专名命中率: A={rr(S['rA'],S['ref_r'])}  B={rr(S['rB'],S['ref_r'])}  (n={S['ref_r']})")
    w(f"全热词命中率:   A={rr(S['tA'],S['ref_t'])}  B={rr(S['tB'],S['ref_t'])}  (n={S['ref_t']})")
    w(f"CER:            A={rr(S['cAn'],S['cAd'])}  B={rr(S['cBn'],S['cBd'])}")
    w(f"echo误插/段:    A={rr(S['echoA'],S['spk'])}  B={rr(S['echoB'],S['spk'])}  (段数={S['spk']})")
    log.close()

if __name__ == "__main__":
    main()
