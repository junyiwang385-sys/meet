#!/usr/bin/env bash
set -u
cd /c/Users/Admin/meet
: > eval/_pc_clean/_rerun3.log
curl -s -m4 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || { OLLAMA_MODELS="E:/ollama-models" "E:/ollama/ollama.exe" serve >/tmp/ollama.log 2>&1 & sleep 6; }
for mid in 20200708_L_R002S07C01 20200709_L_R002S03C01 20200709_L_R002S05C01; do
  od="eval/_pc_clean/$mid"; t0=$(date +%s)
  PYTHONIOENCODING=utf-8 python eval/pc_full_minutes.py "$od/meeting_result.json" "$od" >"$od/run.log" 2>&1
  rc=$?; dt=$(( $(date +%s)-t0 )); ofb=$(ls "$od"/requests/full_summary/fallback_reason.json 2>/dev/null | wc -l)
  if [ -f "$od/meeting_summary.json" ]; then
    echo "$mid ${dt}s rc=$rc ovfb=$ofb OK" >> eval/_pc_clean/_rerun3.log
  else
    echo "$mid rc=$rc FAIL: $(grep -aE Error "$od/run.log" | tail -1)" >> eval/_pc_clean/_rerun3.log
  fi
done
echo "DONE3 @ $(date '+%H:%M:%S')" >> eval/_pc_clean/_rerun3.log
