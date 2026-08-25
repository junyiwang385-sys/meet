#!/usr/bin/env python3
"""Patch board_segment_asr_batch.py to avoid treating Finished markers as ASR text."""

from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/userdata/meeting_agent/scripts/board_segment_asr_batch.py")
text = path.read_text(encoding="utf-8")
original = text

old = """def normalize_transcript(text):\n    text = re.sub(r\"\\x1b\\[[0-9;]*[A-Za-z]\", \"\", text or \"\")\n    text = text.replace(\"\\r\", \"\\n\")\n    lines = []\n    for line in text.splitlines():\n        line = re.sub(r\"\\s+\", \" \", line).strip()\n        if line:\n            lines.append(line)\n    return \"\\n\".join(lines).strip()\n"""

new = """def normalize_transcript(text):\n    text = re.sub(r\"\\x1b\\[[0-9;]*[A-Za-z]\", \"\", text or \"\")\n    text = text.replace(\"\\r\", \"\\n\")\n    lines = []\n    for line in text.splitlines():\n        line = re.sub(r\"\\s+\", \" \", line).strip()\n        if not line:\n            continue\n        # Some empty/silent segments produce only demo boundary markers.\n        if re.fullmatch(r\"[-\\s]*Finished[-\\s]*\", line, flags=re.IGNORECASE):\n            continue\n        lines.append(line)\n    return \"\\n\".join(lines).strip()\n"""

if "re.fullmatch(r\"[-\\\\s]*Finished" in text:
    print("Finished marker filter already present")
    sys.exit(0)

if old not in text:
    raise SystemExit("cannot find normalize_transcript block")

text = text.replace(old, new, 1)
backup = path.with_suffix(path.suffix + ".before_filter_finished_marker")
if not backup.exists():
    backup.write_text(original, encoding="utf-8")
    print(f"backup written: {backup}")
path.write_text(text, encoding="utf-8")
print(f"patched: {path}")
