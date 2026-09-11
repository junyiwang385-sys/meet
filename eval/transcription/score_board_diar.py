# -*- coding: utf-8 -*-
"""点2·板端真实 3D-Speaker 打分:解析 bridge 拉回的 0048 结果里的板端 rttm,
用与 PC CAM++ 相同的 pyannote 口径(非重叠 DER collar0.25 + 纯度/覆盖 + 说话人数)对 rttm 参考打分。
与 PC CAM++(点2)并排,验证板端调优参数把过切压下去多少。"""
from __future__ import annotations
import sys, io, re, pathlib
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = pathlib.Path(r"C:/Users/Admin/meet")
BRIDGE = ROOT/"ops/board-bridge/results/0048_cat_board_3dspk_rttm.out"
OUT = ROOT/"eval/transcription/_out/point2_board_3dspk.txt"
MEETINGS = [("g1","20200707_L_R001S04C01"),("g2","20200708_L_R002S05C01"),("g5","20200709_L_R002S04C01")]
# PC CAM++(点2)对照
PC = {"g1":(0.611,0.781,0.357,"7/7"),"g2":(0.490,0.842,0.573,"7/10"),"g5":(0.317,0.952,0.660,"6/7")}

def ann_from_rttm_lines(lines):
    from pyannote.core import Annotation, Segment
    a = Annotation()
    for ln in lines:
        p = ln.split()
        if len(p) >= 8 and p[0] == "SPEAKER":
            st, du, spk = float(p[3]), float(p[4]), p[7]
            if du > 0: a[Segment(st, st+du)] = spk
    return a

def parse_board(path):
    """从 0048 结果里按 ===RTTM_<mid>=== 切出每场板端 rttm 行。"""
    blocks = {}; cur = None
    for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"===RTTM_(\S+)===", ln)
        if m: cur = m.group(1); blocks[cur] = []; continue
        if ln.startswith("==="): cur = None; continue
        if cur and ln.startswith("SPEAKER"): blocks[cur].append(ln)
    return blocks

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    log = open(OUT, "w", encoding="utf-8")
    def w(*a): s=" ".join(str(x) for x in a); print(s); log.write(s+"\n"); log.flush()

    from pyannote.metrics.diarization import DiarizationErrorRate, DiarizationPurity, DiarizationCoverage
    board = parse_board(BRIDGE)
    der = DiarizationErrorRate(collar=0.25, skip_overlap=True)
    pur = DiarizationPurity(); cov = DiarizationCoverage()
    spk_err = []
    w("场   | 板端 3D-Speaker(DER非重叠/纯度/覆盖/说话人ref→hyp)      || PC CAM++(DER/纯度/覆盖/人数)")
    for tag, mid in MEETINGS:
        ref = ann_from_rttm_lines(pathlib.Path(rf"E:/train_L/TextGrid/{mid}.rttm").read_text(encoding="utf-8").splitlines())
        hyp = ann_from_rttm_lines(board.get(mid, []))
        d = der(ref, hyp, detailed=True); tot = d["total"]
        rspk, hspk = len(ref.labels()), len(hyp.labels()); spk_err.append(abs(rspk-hspk))
        pcd = PC[tag]
        w(f"{tag} | DER={d['diarization error rate']:.3f}[漏{d['missed detection']/tot:.2f} 虚{d['false alarm']/tot:.2f} 混{d['confusion']/tot:.2f}] "
          f"纯{pur(ref,hyp):.3f} 覆{cov(ref,hyp):.3f} {rspk}→{hspk}  ||  DER={pcd[0]} 纯{pcd[1]} 覆{pcd[2]} {pcd[3]}")

    w("\n============ 板端 3D-Speaker 三场合并 ============")
    w(f"DER(非重叠,collar0.25) = {abs(der):.3f}   (PC CAM++ = 0.461)")
    w(f"纯度 Purity   = {abs(pur):.3f}   (PC CAM++ = 0.868)")
    w(f"覆盖 Coverage = {abs(cov):.3f}   (PC CAM++ = 0.519)")
    w(f"说话人数误差均值 = {sum(spk_err)/len(spk_err):.2f} {spk_err}   (PC CAM++ = 1.33 [0,3,1])")
    log.close()

if __name__ == "__main__":
    main()
