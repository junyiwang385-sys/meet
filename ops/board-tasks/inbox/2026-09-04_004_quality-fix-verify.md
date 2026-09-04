# 任务单 004：三处质量修复的板端验证 + 首次长会实测

- **task_id**：2026-09-04_004
- **目的**：验证 003 之后合入的三处修复效果（QA 错配、占位待办、continues_previous 全 false），并第一次在板端跑一场长会（1h+）。
- **关联 commit**：`feature/transcript-postprocess` HEAD = `b92550a`（已 push）
- **板端**：`linaro@10.10.22.36`
- **和 003 的关系**：g1–g5 **用与 003 完全相同的 5 段音频**（temperature=0，同音频跑新代码 = 受控对比），g6 是新增的长会。

> **执行说明**：本单全是复制粘贴命令，**不需要任何判断**。三部分按顺序做：A 在中转机部署，B 在板端跑，C 在中转机回收。命令里的变量已填好，直接整段贴进终端即可。

---

## A. 中转机部署（`D:\Meeting_Agent_mainline`，PowerShell，整段复制）

新代码放**新快照目录** `mainline_b92550a`，**不动** cc9d83e（它是对比基线）。venv 复用 cc9d83e 的（无新依赖）。

```powershell
cd D:\Meeting_Agent_mainline
git fetch origin
git checkout feature/transcript-postprocess
git pull

$BOARD = "linaro@10.10.22.36"
$SNAP  = "/userdata/meeting_agent1/mainline_b92550a"

# 在板端建新快照目录并清掉可能的残留，保证跑的就是本次 HEAD
ssh $BOARD "rm -rf $SNAP/src/meeting_agent && mkdir -p $SNAP/src"
scp -r .\src\meeting_agent "${BOARD}:$SNAP/src/"

# 导入自检（必须打印 harness_import=ok，否则停下反馈）
ssh $BOARD "PYTHONPATH=$SNAP/src /userdata/meeting_agent1/venvs/mainline_cc9d83e/bin/python -c 'import pypinyin, meeting_agent.harness.main, meeting_agent.observability.run_report; print(\"harness_import=ok\")'"
```

**A 段完成判据**：最后一行打印 `harness_import=ok`。

---

## B. 板端运行（SSH 进 `linaro@10.10.22.36` 后，整段复制）

6 组串行跑：g1–g5 = 003 的同 5 段音频，g6 = 长会。每组跑完自动生成 `run_report.json`。

```bash
SNAP=/userdata/meeting_agent1/mainline_b92550a
PY=/userdata/meeting_agent1/venvs/mainline_cc9d83e/bin/python
OUT=/userdata/meeting_agent/output/quality_fix_004
EV=/userdata/meeting_agent/evals/pipeline_outputs/e2e_trainL_full
export PYTHONPATH=$SNAP/src

# g1-g5：与 003 完全相同的 5 段音频（受控对比）
A1=$EV/train_L_20200707_L_R001S04C01/01_segments/input_mono16k.wav
A2=$EV/train_L_20200708_L_R002S05C01/01_segments/input_mono16k.wav
A3=$EV/train_L_20200707_L_R001S03C01/01_segments/input_mono16k.wav
A4=$EV/train_L_20200709_L_R002S08C01/01_segments/input_mono16k.wav
A5=$EV/train_L_20200709_L_R002S04C01/01_segments/input_mono16k.wav
# g6：长会（1h+）
A6=/userdata/meeting_agent/input/L_R004S06C01_full_16k.wav

i=0
for f in "$A1" "$A2" "$A3" "$A4" "$A5" "$A6"; do
  i=$((i+1))
  $PY -m meeting_agent.harness.main --source-audio "$f" --out-dir $OUT/g$i/harness --meeting-id g$i --task-id local-004 --overwrite --enrichment
  $PY -m meeting_agent.observability.run_report $OUT/g$i/harness
done

# 一行汇总，确认 6 组都齐了
for i in 1 2 3 4 5 6; do echo "g$i:"; ls -l $OUT/g$i/harness/run_report.json $OUT/g$i/harness/03_llm_summary/enrichment.json; done
```

**B 段完成判据**：6 组的 `run_report.json` 和 `enrichment.json` 都存在（`ls` 每个都列出、无 No such file）。

---

## C. 中转机回收（`D:\Meeting_Agent_mainline`，PowerShell，整段复制）

只回传小体积 JSON，不传音频/模型/大日志。

```powershell
cd D:\Meeting_Agent_mainline
$BOARD = "linaro@10.10.22.36"
$OUT   = "/userdata/meeting_agent/output/quality_fix_004"
$R     = "ops\board-results\2026-09-04_004_quality-fix-verify"

foreach ($i in 1..6) {
  New-Item -Force -ItemType Directory "$R\g$i" | Out-Null
  scp "${BOARD}:$OUT/g$i/harness/run_report.json"                       "$R\g$i\"
  scp "${BOARD}:$OUT/g$i/harness/run_metrics.json"                      "$R\g$i\"
  scp "${BOARD}:$OUT/g$i/harness/stage_status.json"                     "$R\g$i\"
  scp "${BOARD}:$OUT/g$i/harness/03_llm_summary/enrichment.json"        "$R\g$i\"
  scp "${BOARD}:$OUT/g$i/harness/meeting_summary.json"                  "$R\g$i\"
}

# 自动汇总（不用手填），生成 RESULTS.md
$env:PYTHONPATH = "src"
python eval\run_eval.py --config eval\eval_config_board004.json --out "$R\RESULTS.md"

# 提交回传结果
git add "$R" eval\eval_config_board004.json
git commit -m "data(board-results 004): 质量修复验证6组(含1长会)回传"
git push origin feature/transcript-postprocess
```

**C 段完成判据**：`RESULTS.md` 生成、git push 成功。

---

## 需要回传的东西（就是 C 段做的）

每组 5 个小 JSON：`run_report.json` / `run_metrics.json` / `stage_status.json` / `enrichment.json` / `meeting_summary.json`，共 6 组，加自动生成的 `RESULTS.md`。**不要回传** 音频、模型、requests/ 目录、原始 rkllm_server.log。

---

## 出错就停，按这个反馈（不要自己改命令重试）

- A 段 `harness_import=ok` 没出现 → 把 ssh 那行的完整报错贴回来
- B 段某组报错 → 把那一组的终端输出 + `cat $OUT/gN/harness/stage_status.json` 贴回来，**继续跑剩余组**（各组独立）
- C 段 scp 报 No such file → 说明该组板端没跑成，回到 B 段看那组

---

## 开发机判读要点（回传后我自己看，实验机不用管）

对照 003 的 g1–g5，重点看四项是否改善：
1. `run_report.blocks.continues_previous_count` 是否脱离 0（003 是 0/40 全 false）
2. enrichment QA 是否还有答非所问/重复
3. action_items 是否还有「明确待办」占位
4. `run_report.memory.server_rss_peak_mb` 是否已填（003 是 None，本次代码已修）
5. g6 长会：是否跑通、RTF、内存峰值、是否触发 split/retry —— 项目头牌主张首验
