#!/usr/bin/env python3
"""Patch infer_diarization_rknn.py to clamp RKNN VAD scores above zero.

RKNN3 returns FP16 tensors. Very small positive VAD posterior values can become
exactly 0 after FP16 conversion. FunASR's VAD postprocess calls math.log(sum_score),
so an all-zero class sum can raise ValueError: math domain error.
"""

from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("speakerlab/bin/infer_diarization_rknn.py")
text = path.read_text(encoding="utf-8")
original = text

needle_seq = "scores_np = logits.reshape(1, total_frames, 248).astype(np.float32, copy=False)\n"
replace_seq = needle_seq + (
    "        # RKNN FP16 may underflow tiny positive VAD posteriors to exactly 0.\n"
    "        # FunASR VAD postprocess calls math.log(sum_score), so keep scores positive.\n"
    "        scores_np = np.maximum(scores_np, 1.0e-12).astype(np.float32, copy=False)\n"
)

needle_old = "scores_np = np.concatenate(logits_parts, axis=1).astype(np.float32, copy=False)\n"
replace_old = needle_old + (
    "        # RKNN FP16 may underflow tiny positive VAD posteriors to exactly 0.\n"
    "        # FunASR VAD postprocess calls math.log(sum_score), so keep scores positive.\n"
    "        scores_np = np.maximum(scores_np, 1.0e-12).astype(np.float32, copy=False)\n"
)

if "scores_np = np.maximum(scores_np, 1.0e-12)" in text:
    print("VAD score floor patch already present")
    sys.exit(0)

if needle_seq in text:
    text = text.replace(needle_seq, replace_seq, 1)
elif needle_old in text:
    text = text.replace(needle_old, replace_old, 1)
else:
    raise SystemExit("cannot find RKNN VAD scores_np assignment")

backup = path.with_suffix(path.suffix + ".before_vad_score_floor")
if not backup.exists():
    backup.write_text(original, encoding="utf-8")
    print(f"backup written: {backup}")

path.write_text(text, encoding="utf-8")
print(f"patched: {path}")
