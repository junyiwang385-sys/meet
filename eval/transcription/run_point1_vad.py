# -*- coding: utf-8 -*-
"""点1·VAD 评测(标准口径):系统真实 VAD(FunASR fsmn-vad)语音轴 vs TextGrid 参考语音轴。
参考:TextGrid 中所有 tier 里【有文本】的 interval 并集 = 语音;其余 = 非语音。
帧级(10ms)对齐,报:
  Miss率 = 漏检语音帧/参考语音帧   (↑=丢语音=ASR 少字的上游源头)
  FA率   = 虚检语音帧/参考非语音帧 (↑=噪声/静音被当语音送进 ASR)
  DetER  = (漏+虚)/参考语音帧 (pyannote DetectionErrorRate 口径)
n=3。CPU 即可(fsmn-vad 很小)。"""
from __future__ import annotations
import sys, io, pathlib, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
sys.path[:0] = [str(ROOT/"eval"/"transcription"), str(ROOT/"eval"/"golden_v2")]
from build_timeline import parse_textgrid
from normalize import normalize_zh

MEETINGS = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]
OUT = ROOT/"eval/transcription/_out/point1_vad_n3.txt"
FR = 0.01  # 10ms 帧

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    log = open(OUT, "w", encoding="utf-8")
    def w(*a): s=" ".join(str(x) for x in a); print(s); log.write(s+"\n"); log.flush()

    import numpy as np, soundfile as sf
    from funasr import AutoModel
    w("[VAD] 载入 fsmn-vad ...")
    vad = AutoModel(model="fsmn-vad", disable_update=True)
    w("[VAD] ok\n")

    COLLAR = 0.25  # 标准边界宽恕(秒),消除话语级参考的边界不精确
    tot = {"miss":0,"fa_c":0,"ref_sp":0,"ref_ns_c":0}
    cov_all = []          # 每条参考话语的 VAD 覆盖率
    w("注:AliMeeting TextGrid 是【话语级】参考(区间含内部停顿),帧级 Miss 会被系统性高估;")
    w("   故主看 ①带collar的FA(VAD干净度)②话语覆盖率(真正的信息丢失代理)。\n")
    for tag, mid in MEETINGS:
        segs = [s for s in parse_textgrid(rf"E:/train_L/TextGrid/{mid}.TextGrid") if normalize_zh(s.get("text",""))]
        audio, sr = sf.read(rf"E:/train_L/wav/{mid}.flac", dtype="float32")
        if audio.ndim == 2: audio = audio.mean(axis=1)
        dur = len(audio)/sr; nfr = int(dur/FR)+1
        ref = np.zeros(nfr, dtype=bool)
        for s in segs:
            a=int(s["start_ms"]/1000/FR); b=min(nfr, int(s["end_ms"]/1000/FR)+1); ref[a:b]=True

        tmp = pathlib.Path(tempfile.gettempdir())/f"vad_{mid}.wav"
        sf.write(str(tmp), audio, sr, subtype="PCM_16")
        segs_vad = vad.generate(input=str(tmp))[0]["value"]
        sysb = np.zeros(nfr, dtype=bool)
        for a_ms,b_ms in segs_vad:
            a=int(a_ms/1000/FR); b=min(nfr,int(b_ms/1000/FR)+1); sysb[max(0,a):b]=True
        try: tmp.unlink()
        except OSError: pass

        # collar:参考语音/非语音边界前后 COLLAR 秒不计
        c = int(COLLAR/FR); bnd = np.zeros(nfr, bool)
        for idx in np.where(np.diff(ref.astype(int)) != 0)[0]:
            bnd[max(0,idx-c):idx+c+1] = True
        m = ~bnd
        miss = int((ref & ~sysb & m).sum()); fa_c = int((~ref & sysb & m).sum())
        ref_sp = int((ref & m).sum()); ref_ns_c = int((~ref & m).sum())
        for k,v in (("miss",miss),("fa_c",fa_c),("ref_sp",ref_sp),("ref_ns_c",ref_ns_c)): tot[k]+=v

        # 话语级覆盖率:每条参考话语被 VAD 覆盖的帧占比 +(时长,用于过滤短背景音)
        covs=[]
        for s in segs:
            a=int(s["start_ms"]/1000/FR); b=min(nfr,int(s["end_ms"]/1000/FR)+1)
            if b>a: covs.append((sysb[a:b].mean(), (s["end_ms"]-s["start_ms"])/1000))
        cov_all += covs
        cv=np.array([c for c,_ in covs]); dv=np.array([d for _,d in covs])
        sub=dv>2.0  # 只看 >2s 的实义话语
        w(f"{tag} {mid} VAD语音{sysb.mean():.0%}(参考松={ref.mean():.0%}) | FA(collar)={fa_c/ref_ns_c:.3f} | "
          f"话语覆盖中位={np.median(cv):.2f} | >2s实义话语全丢(<20%)={np.mean(cv[sub]<0.2):.1%}(n={sub.sum()})")

    cov=np.array([c for c,_ in cov_all]); dur_a=np.array([d for _,d in cov_all]); sub=dur_a>2.0
    rr=lambda n,d:(round(n/d,4) if d else None)
    w("\n================ 点1 VAD 三场合并 ================")
    w(f"FA率(collar 0.25s) = {rr(tot['fa_c'],tot['ref_ns_c'])}  ← VAD 干净度(越低越好):噪声/静音被当语音送进 ASR")
    w(f"话语覆盖率 中位     = {np.median(cov):.2f}   (VAD 覆盖每条参考话语的比例;切内部停顿属正常)")
    w(f"真·信息丢失(>2s实义话语覆盖<20%) = {np.mean(cov[sub]<0.2):.1%}  (n={int(sub.sum())})  ← 整句实义话没进 ASR")
    w(f"  (对比:含短背景音的全部话语<20% = {np.mean(cov<0.2):.1%},差值即被过滤掉的短促/背景音)")
    w(f"帧级 Miss(collar) = {rr(tot['miss'],tot['ref_sp'])}  ⚠️【非VAD质量指标】被话语级参考内部停顿高估,仅存档")
    w(f"(参考话语总数 n={len(cov)},其中 >2s 实义 {int(sub.sum())})")
    log.close()

if __name__ == "__main__":
    main()
