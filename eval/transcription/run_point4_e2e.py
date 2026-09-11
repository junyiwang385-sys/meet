# -*- coding: utf-8 -*-
"""点4·端到端转写 + 归因(标准口径):系统全链 CAM++分离→同说话人合并切块→Qwen3-ASR→按时间拼整会转写,
与 TextGrid 全文比端到端 CER。与点3(金标切分 CER)作差=前端(VAD+切分+聚类)引入的额外损失。
最后打印点1/2/3/4 合并归因表。n=3,ASR 走 GPU。"""
from __future__ import annotations
import sys, io, json, pathlib, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path[:0] = [str(ROOT/"eval"/"transcription"), str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh
from score_asr import cer_counts, rate

MEETINGS = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]
OUT = ROOT/"eval/transcription/_out/point4_e2e_n3.txt"
MERGE_GAP, MAX_SEG, PAD = 1.0, 30.0, 0.2
# 点1/2/3 已跑出的合并结果(存档,用于归因表)
P1 = {"fa":0.115, "info_loss":0.104}
P2 = {"der":0.461, "conf":0.10, "purity":0.868, "cov":0.519}
P3_CER = 0.150

def merge_segs(segs):
    """CAM++ 段按时间排序,合并相邻同说话人(gap<MERGE_GAP,长度<MAX_SEG)。"""
    segs = sorted(segs, key=lambda x: x[0])
    out = []
    for s, e, spk in segs:
        if out and out[-1][2] == spk and s - out[-1][1] <= MERGE_GAP and (e - out[-1][0]) <= MAX_SEG:
            out[-1][1] = e
        else:
            out.append([s, e, spk])
    return out

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    log = open(OUT, "w", encoding="utf-8")
    def w(*a): s=" ".join(str(x) for x in a); print(s); log.write(s+"\n"); log.flush()

    import torch, soundfile as sf
    from transformers import Qwen3ASRForConditionalGeneration, AutoProcessor
    from modelscope.pipelines import pipeline
    from modelscope.utils.constant import Tasks
    DEV = "cuda" if torch.cuda.is_available() else "cpu"
    w("[load] Qwen3-ASR + CAM++ ...")
    proc = AutoProcessor.from_pretrained(r"E:/models/Qwen3-ASR-0.6B-hf")
    model = Qwen3ASRForConditionalGeneration.from_pretrained(r"E:/models/Qwen3-ASR-0.6B-hf", dtype=torch.float32).to(DEV).eval()
    sd = pipeline(task=Tasks.speaker_diarization, model="iic/speech_campplus_speaker-diarization_common")
    w("[load] ok\n")

    def asr(clip):
        inp = proc.apply_transcription_request(audio=clip, language="Chinese", prompt=None, sampling_rate=16000).to(DEV)
        with torch.no_grad():
            g = model.generate(**inp, max_new_tokens=200, do_sample=False)
        return proc.batch_decode(g[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()

    e2e = {"s":0,"d":0,"i":0,"n":0}
    for tag, mid in MEETINGS:
        segs_ref = [s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if normalize_zh(s.get("text",""))]
        ref_full = "".join(normalize_zh(s["text"]) for s in sorted(segs_ref, key=lambda x:x["start_ms"]))
        audio, sr = sf.read(rf"E:/train_L/wav/{mid}.flac", dtype="float32")
        if audio.ndim == 2: audio = audio.mean(axis=1)
        tmp = pathlib.Path(tempfile.gettempdir())/f"e2e_{mid}.wav"; sf.write(str(tmp), audio, sr, subtype="PCM_16")
        dseg = [(float(a),float(b),int(k)) for a,b,k in sd(str(tmp))["text"]]
        try: tmp.unlink()
        except OSError: pass
        merged = merge_segs(dseg)
        parts = []
        for i,(a,b,spk) in enumerate(merged):
            c = audio[int(max(0,a-PAD)*sr):int(min(len(audio)/sr,b+PAD)*sr)]
            if len(c) < 0.3*sr: continue
            try: parts.append((a, asr(c)))
            except Exception as ex: w(f"  [{tag} seg{i} ERR]", repr(ex)[:100])
            if i % 30 == 0: w(f"  ..{tag} seg {i+1}/{len(merged)}")
        hyp_full = "".join(normalize_zh(t) for _,t in sorted(parts, key=lambda x:x[0]))
        cc = cer_counts(ref_full, hyp_full)
        for k in e2e: e2e[k]+=cc[k]
        w(f"{tag} {mid} | 端到端CER={rate(cc['s'],cc['d'],cc['i'],cc['n'])} (S={cc['s']} D={cc['d']} I={cc['i']} N={cc['n']}) | CAM++段{len(dseg)}→合并{len(merged)}")

    e2e_cer = rate(e2e["s"],e2e["d"],e2e["i"],e2e["n"])
    w(f"\n端到端 CER(合并) = {e2e_cer}  (S={e2e['s']} D={e2e['d']} I={e2e['i']} N={e2e['n']})")

    w("\n================ 转写评测线·合并归因表(n=3,PC等价·标准口径) ================")
    w(f"{'环节':<10}{'指标':<28}{'结果':<12}{'说明'}")
    w(f"{'-'*72}")
    w(f"{'点1 VAD':<10}{'FA(collar0.25)':<28}{P1['fa']:<12}{'噪声进ASR比例(g2偏高)'}")
    w(f"{'':<10}{'真信息丢失(>2s话语全丢)':<24}{P1['info_loss']:<12}{'~10%实义话语整句没进ASR=召回天花板'}")
    w(f"{'点2 分离':<10}{'说话人混淆':<26}{P2['conf']:<12}{'归错人~10%(低=不张冠李戴)'}")
    w(f"{'':<10}{'纯度/覆盖':<27}{str(P2['purity'])+'/'+str(P2['cov']):<12}{'纯度高覆盖低=过切(宁散不混)'}")
    w(f"{'点3 ASR':<10}{'CER(金标切分)':<27}{P3_CER:<12}{'ASR本身:排除前端污染'}")
    w(f"{'':<10}{'B-WER(role专名)':<26}{'0.186→0.083':<12}{'热词偏置砍半(已验证)'}")
    w(f"{'点4 端到端':<10}{'CER(系统全链)':<26}{e2e_cer:<12}{'VAD+切分+聚类+ASR 叠加'}")
    w(f"{'归因':<10}{'前端额外损失=点4−点3':<24}{round(e2e_cer-P3_CER,3):<12}{'切分/VAD/聚类相对完美切分多丢的'}")
    log.close()

if __name__ == "__main__":
    main()
