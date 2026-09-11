# -*- coding: utf-8 -*-
"""点3·ASR 隔离评测(标准口径):金标切分逐段喂 HF Qwen3-ASR,A组不塞热词/B组塞热词。
指标:CER(jiwer,含S/D/I) + B-WER(role专名)/U-WER(其余) + role插入率(echo)。n=3场。
偏置词打分集=role专名(干净);注入 prompt=role+core_facts专名类anchor(=会前名单近似)。
跑 GPU(pico-embed venv);model+inputs 用 float32。结果写 out(UTF-8)。"""
from __future__ import annotations
import sys, json, pathlib, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path[:0] = [str(ROOT/"eval"/"transcription"), str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from score_asr import cer_counts, bwer_counts, rate
from normalize import normalize_zh

MODEL_DIR = r"E:/models/Qwen3-ASR-0.6B-hf"
MEETINGS = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]
OUT = ROOT/"eval/transcription/_out/point3_asr_n3.txt"
MAX_CLIPS, PAD = 40, 0.2
_HAN = lambda t: bool(re.fullmatch(r"[\u4e00-\u9fff]{2,8}", t or ""))

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    log = open(OUT, "w", encoding="utf-8")
    def w(*a): s=" ".join(str(x) for x in a); print(s); log.write(s+"\n"); log.flush()

    import torch, soundfile as sf
    from transformers import Qwen3ASRForConditionalGeneration, AutoProcessor
    DEV = "cuda" if torch.cuda.is_available() else "cpu"
    w("[模型] 载入", MODEL_DIR, "device=", DEV)
    proc = AutoProcessor.from_pretrained(MODEL_DIR)
    model = Qwen3ASRForConditionalGeneration.from_pretrained(MODEL_DIR, dtype=torch.float32).to(DEV).eval()
    w("[模型] ok\n")

    def transcribe(wav, prompt):
        inp = proc.apply_transcription_request(audio=wav, language="Chinese", prompt=prompt, sampling_rate=16000).to(DEV)
        with torch.no_grad():
            gen = model.generate(**inp, max_new_tokens=128, do_sample=False)
        return proc.batch_decode(gen[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()

    # 累计器
    def zc(): return {"s":0,"d":0,"i":0,"n":0}
    def zb(): return {"B":{"ref":0,"s":0,"d":0,"i":0},"U":{"ref":0,"s":0,"d":0,"i":0}}
    CER={"A":zc(),"B":zc()}; BW={"A":zb(),"B":zb()}
    def add_c(dst,c): [dst.__setitem__(k,dst[k]+c[k]) for k in c]
    def add_b(dst,b): [dst[g].__setitem__(k,dst[g][k]+b[g][k]) for g in("B","U") for k in b[g]]

    for tag, mid in MEETINGS:
        g = json.loads((ROOT/"eval/golden_v2/out"/f"{mid}.golden.json").read_text(encoding="utf-8"))
        roles = list(dict.fromkeys(s.get("role","").strip() for s in g.get("speakers",[]) if len(s.get("role","").strip())>=2))
        anchors = [a for f in (g.get("core_facts") or []) for a in (f.get("anchors") or [])]
        prompt = "、".join(dict.fromkeys(roles + [a for a in anchors if _HAN(a)]))   # 注入=role+专名anchor
        score_terms = roles                                                          # B-WER打分集=role干净专名
        segs = [s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if normalize_zh(s.get("text",""))]
        rset = set(roles)
        # 取含 role 专名的区间优先,再补普通区间,凑 MAX_CLIPS
        with_role = [s for s in segs if any(t in normalize_zh(s["text"]) for t in rset)]
        others = [s for s in segs if s not in with_role]
        clips = (with_role[:MAX_CLIPS] + others)[:MAX_CLIPS]
        audio, sr = sf.read(rf"E:/train_L/wav/{mid}.flac", dtype="float32")
        if audio.ndim == 2: audio = audio.mean(axis=1)
        w(f"==== {tag} {mid} roles={len(roles)} 注入热词={prompt.count('、')+1} 含role区间={len(with_role)} 取{len(clips)} ====")
        for i, s in enumerate(clips):
            a=max(0,s["start_ms"]/1000-PAD); b=min(len(audio)/sr, s["end_ms"]/1000+PAD)
            clip=audio[int(a*sr):int(b*sr)]
            if len(clip) < 0.3*sr: continue
            ref=s["text"]
            try:
                hA=transcribe(clip,None); hB=transcribe(clip,prompt)
            except Exception as e:
                w(f"  [clip {i} ERR]", repr(e)[:150]); continue
            add_c(CER["A"], cer_counts(ref,hA)); add_c(CER["B"], cer_counts(ref,hB))
            add_b(BW["A"], bwer_counts(ref,hA,score_terms)); add_b(BW["B"], bwer_counts(ref,hB,score_terms))
            if i%10==0: w(f"  ..{tag} {i+1}/{len(clips)}")

    w("\n================ 点3 标准口径结果(n=3,含role区间优先) ================")
    for arm in ("A","B"):
        c=CER[arm]; b=BW[arm]["B"]; u=BW[arm]["U"]
        name = "A组·不塞热词(基线)" if arm=="A" else "B组·塞热词"
        w(f"[{name}]")
        w(f"  CER   = {rate(c['s'],c['d'],c['i'],c['n'])}  (S={c['s']} D={c['d']} I={c['i']} N={c['n']})")
        w(f"  B-WER = {rate(b['s'],b['d'],b['i'],b['ref'])}  (role专名; S={b['s']} D={b['d']} I={b['i']} ref={b['ref']})  ← 越低越好")
        w(f"  U-WER = {rate(u['s'],u['d'],u['i'],u['ref'])}  (其余; ref={u['ref']})")
        w(f"  role插入(echo) = {b['i']} 次\n")
    log.close()

if __name__ == "__main__":
    main()
