#!/usr/bin/env python3
"""Patch board_segment_asr_batch.py to drop demo Finished markers after extraction."""

from pathlib import Path
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/userdata/meeting_agent/scripts/board_segment_asr_batch.py")
text = path.read_text(encoding="utf-8")
original = text

needle = "    text, method = extract_asr_transcript_from_text(raw, mode=args.asr_mode, regex=args.asr_transcript_regex)\n"
insert = needle + (
    "    if re.fullmatch(r\"[-\\s]*Finished[-\\s]*\", (text or \"\").strip(), flags=re.IGNORECASE):\n"
    "        text = \"\"\n"
    "        method = method + \"+drop_finished_marker\"\n"
)

if "drop_finished_marker" in text:
    print("drop Finished marker patch already present")
    sys.exit(0)

if needle not in text:
    raise SystemExit("cannot find ASR extraction line")

text = text.replace(needle, insert, 1)
backup = path.with_suffix(path.suffix + ".before_drop_finished_marker")
if not backup.exists():
    backup.write_text(original, encoding="utf-8")
    print(f"backup written: {backup}")
path.write_text(text, encoding="utf-8")
print(f"patched: {path}")
