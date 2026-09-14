#!/usr/bin/env bash
# 30 场干净输入全流程 runner。以分离进程运行,写进度到 _progress.log,与 harness 任务生命周期解耦。
set -u
cd /c/Users/Admin/meet
PROG="eval/_pc_clean/_progress.log"
: > "$PROG"
# 确保 ollama
curl -s -m4 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 || {
  OLLAMA_MODELS="E:/ollama-models" "E:/ollama/ollama.exe" serve >/tmp/ollama.log 2>&1 &
  sleep 6
}
mids=$(ls eval/golden_v2/timelines/*.timeline.txt | xargs -n1 basename | sed 's/.timeline.txt//' | sort)
n=$(echo "$mids" | wc -l); i=0
echo "重跑 $n 场(硬化后·分离进程) @ $(date '+%H:%M:%S')" >> "$PROG"
for mid in $mids; do
  i=$((i+1)); od="eval/_pc_clean/$mid"
  PYTHONIOENCODING=utf-8 python eval/golden_v2/timeline_to_result.py "$mid" >/dev/null 2>&1
  t0=$(date +%s)
  PYTHONIOENCODING=utf-8 python eval/pc_full_minutes.py "$od/meeting_result.json" "$od" >"$od/run.log" 2>&1
  rc=$?; dt=$(( $(date +%s)-t0 )); fb=$(ls "$od"/blocks/*/fallback_reason.json 2>/dev/null | wc -l)
  if [ -f "$od/meeting_summary.json" ]; then
    stats=$(python -c "import json,pathlib as P;s=json.loads(P.Path('$od/meeting_summary.json').read_text(encoding='utf-8'));e=P.Path('$od/enrichment.json');en=json.loads(e.read_text(encoding='utf-8')) if e.exists() else {};print(f\"ch={len(s.get('chapters') or [])} spk={len(s.get('speakers') or [])} act={len(s.get('action_items') or [])} dec={len(en.get('decisions') or [])}\")" 2>/dev/null)
    echo "[$i/$n] $mid ${dt}s rc=$rc fb=$fb $stats" >> "$PROG"
  else
    echo "[$i/$n] $mid ${dt}s rc=$rc fb=$fb FAIL: $(grep -aE 'Error' "$od/run.log" 2>/dev/null | tail -1)" >> "$PROG"
  fi
done
echo "完成 @ $(date '+%H:%M:%S')" >> "$PROG"
