#!/usr/bin/env python3
"""Fix indentation of the RKNN VAD score floor patch."""

from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("speakerlab/bin/infer_diarization_rknn.py")
lines = path.read_text(encoding="utf-8").splitlines()
original = "\n".join(lines) + "\n"

out = []
changed = False
i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.lstrip()
    out.append(line)

    if stripped.startswith("scores_np = logits.reshape(") or stripped.startswith("scores_np = np.concatenate("):
        indent = line[: len(line) - len(stripped)]
        # Drop an existing malformed score-floor block if present right after this line.
        j = i + 1
        while j < len(lines) and (
            lines[j].strip().startswith("# RKNN FP16 may underflow")
            or lines[j].strip().startswith("# FunASR VAD postprocess")
            or lines[j].strip().startswith("scores_np = np.maximum(scores_np")
        ):
            j += 1
            changed = True
        out.append(indent + "# RKNN FP16 may underflow tiny positive VAD posteriors to exactly 0.")
        out.append(indent + "# FunASR VAD postprocess calls math.log(sum_score), so keep scores positive.")
        out.append(indent + "scores_np = np.maximum(scores_np, 1.0e-12).astype(np.float32, copy=False)")
        i = j
        changed = True
        continue

    i += 1

new_text = "\n".join(out) + "\n"
if new_text == original and not changed:
    print("no changes made")
    sys.exit(0)

backup = path.with_suffix(path.suffix + ".before_vad_score_floor_indent_fix")
if not backup.exists():
    backup.write_text(original, encoding="utf-8")
    print(f"backup written: {backup}")

path.write_text(new_text, encoding="utf-8")
print(f"patched: {path}")
