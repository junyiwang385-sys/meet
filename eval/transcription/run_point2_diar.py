# -*- coding: utf-8 -*-
"""点2·说话人分离/聚类评测(标准口径):系统 3D-Speaker CAM++ diarization vs rttm 参考。
指标(pyannote.metrics):
  DER(非重叠, collar 0.25s) 及分量(漏检/虚检/说话人混淆)
  纯度 Purity / 覆盖 Coverage(聚类质量对)
  说话人数估计(ref vs hyp)
非重叠 DER = 更公平的口径(远场重叠段本就难,先不罚)。n=3。"""
from __future__ import annotations
import sys, io, pathlib, tempfile, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
OUT = ROOT/"eval/transcription/_out/point2_diar_n3.txt"
MEETINGS = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]

def load_rttm(path):
    from pyannote.core import Annotation, Segment
    ann = Annotation()
    for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if len(p) >= 8 and p[0] == "SPEAKER":
            st, du, spk = float(p[3]), float(p[4]), p[7]
            if du > 0: ann[Segment(st, st+du)] = spk
    return ann

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    log = open(OUT, "w", encoding="utf-8")
    def w(*a): s=" ".join(str(x) for x in a); print(s); log.write(s+"\n"); log.flush()

    import soundfile as sf
    from pyannote.core import Annotation, Segment
    from pyannote.metrics.diarization import DiarizationErrorRate, DiarizationPurity, DiarizationCoverage
    from modelscope.pipelines import pipeline
    from modelscope.utils.constant import Tasks
    w("[diar] 载入 3D-Speaker CAM++ ...")
    sd = pipeline(task=Tasks.speaker_diarization, model="iic/speech_campplus_speaker-diarization_common")
    w("[diar] ok\n")

    der = DiarizationErrorRate(collar=0.25, skip_overlap=True)
    pur = DiarizationPurity(); cov = DiarizationCoverage()
    spk_err = []
    for tag, mid in MEETINGS:
        ref = load_rttm(rf"E:/train_L/TextGrid/{mid}.rttm")
        audio, sr = sf.read(rf"E:/train_L/wav/{mid}.flac", dtype="float32")
        if audio.ndim == 2: audio = audio.mean(axis=1)
        tmp = pathlib.Path(tempfile.gettempdir())/f"diar_{mid}.wav"
        sf.write(str(tmp), audio, sr, subtype="PCM_16")
        res = sd(str(tmp))
        try: tmp.unlink()
        except OSError: pass
        hyp = Annotation()
        for s,e,spk in res["text"]:
            if float(e) > float(s): hyp[Segment(float(s), float(e))] = f"spk{int(spk)}"
        d = der(ref, hyp, detailed=True)
        tot = d["total"]
        rspk = len(ref.labels()); hspk = len(hyp.labels()); spk_err.append(abs(rspk-hspk))
        w(f"{tag} {mid} | DER(非重叠)={d['diarization error rate']:.3f} "
          f"[漏={d['missed detection']/tot:.3f} 虚={d['false alarm']/tot:.3f} 混淆={d['confusion']/tot:.3f}] "
          f"| 纯度={pur(ref,hyp):.3f} 覆盖={cov(ref,hyp):.3f} | 说话人 ref={rspk} hyp={hspk}")

    w("\n================ 点2 说话人分离 三场合并 ================")
    w(f"DER(非重叠,collar0.25) = {abs(der):.3f}  ← 主指标(漏+虚+混淆)/总时长,越低越好")
    w(f"  纯度 Purity   = {abs(pur):.3f}   (系统每个簇内是否同一人;↑好)")
    w(f"  覆盖 Coverage = {abs(cov):.3f}   (同一人是否被归进同一簇;↑好)")
    w(f"说话人数误差(|ref-hyp|均值) = {sum(spk_err)/len(spk_err):.2f}  (3场分别 {spk_err})")
    log.close()

if __name__ == "__main__":
    main()
