#!/usr/bin/env bash
set -u
cd /c/Users/Admin/meet
PROG="eval/_pc_clean_a2/_prog.log"; mkdir -p eval/_pc_clean_a2; : > "$PROG"
curl -s -m4 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || { OLLAMA_MODELS="E:/ollama-models" "E:/ollama/ollama.exe" serve >/tmp/ollama.log 2>&1 & sleep 6; }
# g1 已跑;补 g2/g3/g5 + 一场
MIDS="20200708_L_R002S05C01 20200707_L_R001S03C01 20200709_L_R002S04C01 20200706_L_R001S01C01"
echo "开始 A2 回归 @ $(date '+%H:%M:%S')" >> "$PROG"
for mid in $MIDS; do
  od="eval/_pc_clean_a2/$mid"; t0=$(date +%s)
  PYTHONIOENCODING=utf-8 python eval/pc_full_minutes.py "eval/_pc_clean/$mid/meeting_result.json" "$od" >"$od.log" 2>&1
  rc=$?; dt=$(( $(date +%s)-t0 ))
  nd=$(python -c "import json,pathlib as P;s=json.loads(P.Path('$od/meeting_summary.json').read_text(encoding='utf-8'));print(len(s.get('decisions') or []))" 2>/dev/null)
  echo "$mid ${dt}s rc=$rc decisions=$nd" >> "$PROG"
done
echo "A2 全跑完 @ $(date '+%H:%M:%S')" >> "$PROG"
