# 任务单：enrichment 接入主链路 + 板端 4B 实机验证

- **task_id**：2026-09-02_003
- **创建**：开发端（本机）
- **目的**：本轮把 **enrichment（关键词/问答/金句/决策/层级大纲）接进 harness 主链路**，并让它**复用摘要 stage 已启动的同一个 rkllm server**（不二次加载模型）。请板端验证：①全链路跑通到导出 + 产出 `enrichment.json`；②server **每轮只加载一次**；③出耗时/内存数（4B 实机）。
- **实验设计**：从库里**随机抽 5 段会议音频（g1–g5，各跑一次）**，长度不限定（大致几十分钟量级）。随机抽样避免挑样本偏差，测跨会泛化：接线正确性、enrichment 五类在不同题材/长度会上的产出、耗时/内存分布（5 个数据点）。回传时**记录每段的时长**，便于把耗时/内存按长度对齐看。
- **关联 commit**：见本次 push（`feature/transcript-postprocess`，HEAD）
- **本次板端地址**：待中转机确认（历史 `10.10.22.26/32/36`）

## 本轮改动（相对上次板端 build）

- `stages/product_summary.py`：`run_product_summary_stage` 新增可选 `session` 入参——**传入则复用且不 close**（谁开谁关）；不传维持原样（向后兼容）。
- `stages/enrichment.py`：新增 `run_enrichment_stage` + `make_session_llm_call`（把 `session.request` 包成 enrichment 的 LlmCall，自动加 `/no_think`、失败返 `{}` 不抛）。
- `harness/pipeline.py`：pipeline 持有 `summary_session`，摘要→enrichment 复用同一 server，`finally` 统一 close；enrichment 为独立 stage，**失败不阻断主流程**，写 `enrichment.json` + `result["enrichment"]`。
- `harness/main.py`：新增 `--enrichment`/`--no-enrichment`（**默认开**）。
- `observability/run_report.py`：结构化日志自足化——新增 enrichment 五类计数/金句保真、内存峰值/泄漏、server（含 `loaded_once`）、各 stage status+error 段。**板端需覆盖到新版才有这些段**（见下"全量覆盖"）。
- **不涉及**：diar/ASR 板端脚本、模型、老 `prompts/*_zh.txt`（死层，勿动）。

## 前置检查（中转机先确认）

- [ ] `D:\Meeting_Agent_mainline` 已 `git pull` 到本次 push 的 `feature/transcript-postprocess`
- [ ] 板端 SSH 连通（地址已确认）
- [ ] 从音频库**随机抽 5 段非敏感会议**（g1–g5，长度不限，记录各自时长）；1–2h 长会卖点留待后续单独任务

## 板端步骤（`/userdata/meeting_agent`，≤3 条，无感叹号）

先把随机抽的 5 段文件名填进 `A`，循环跑并**在板端就地生成结构化日志 `run_report.json`**（纯标准库，板端可跑）：

```bash
cd /userdata/meeting_agent && A="a1.wav a2.wav a3.wav a4.wav a5.wav"; i=0; for f in $A; do i=$((i+1)); PYTHONPATH=/userdata/meeting_agent1/mainline_v2/src python -m meeting_agent.harness.main --source-audio input/$f --out-dir output/enrich_verify/g$i/harness --overwrite; done
for i in 1 2 3 4 5; do PYTHONPATH=/userdata/meeting_agent1/mainline_v2/src python -m meeting_agent.observability.run_report output/enrich_verify/g$i/harness; done
ls -l output/enrich_verify/g*/harness/run_report.json output/enrich_verify/g*/harness/03_llm_summary/enrichment.json
```

（enrichment 默认开；如需关闭对照加 `--no-enrichment`。）

## 中转机步骤（`D:\Meeting_Agent_mainline`，PowerShell）

```powershell
git pull
# 【全量覆盖板端包】先删后拷、拷到父目录 src\ ——避免 scp -r 目标已存在时嵌套成 .../meeting_agent/meeting_agent，
# 也清掉旧版已删除的残留文件，保证板端跑的就是本次 HEAD（含新 run_report.py）。
ssh <board> "rm -rf /userdata/meeting_agent1/mainline_v2/src/meeting_agent"
scp -r .\src\meeting_agent <board>:/userdata/meeting_agent1/mainline_v2/src/

# 板端跑完后，只回传小体积结构化日志（run_report.json 已自带 enrichment/内存/server/各 stage status+error）：
$R = "ops\board-results\2026-09-02_003_enrichment-wire-board-verify"
foreach ($i in 1..5) {
  New-Item -Force -ItemType Directory "$R\g$i" | Out-Null
  scp <board>:/userdata/meeting_agent/output/enrich_verify/g$i/harness/run_report.json "$R\g$i\"
  scp <board>:/userdata/meeting_agent/output/enrich_verify/g$i/harness/03_llm_summary/enrichment.json "$R\g$i\"
}
# 自动汇总（零手填）——run_eval 读 5 个 run_report.json 直接出表
$env:PYTHONPATH = "src"; python eval\run_eval.py --config eval\eval_config_board003.json --out "$R\RESULTS.md"
```

## 期望产物

- **板端**：每组 `output/enrich_verify/gN/harness/run_report.json`（自带时长/时延/各 stage 耗时/enrichment 五类计数/内存峰值/server 就绪/红旗）+ `03_llm_summary/enrichment.json`。
- **仓库**：`ops/board-results/2026-09-02_003.../gN/{run_report.json,enrichment.json}` + 自动生成的 `RESULTS.md`。

## 回传要求（中转机 → 仓库）—— 不手填，直接吃结构化日志

- 提交 **5 组 `run_report.json` + `enrichment.json`**（都小）到 `ops/board-results/2026-09-02_003.../gN/`。
- 跑 `run_eval.py` **自动生成 `RESULTS.md`**（汇总表：时长/耗时/摘要vs enrich 耗时/五类计数/金句保真/内存峰值/泄漏/红旗，全部来自结构化日志）。
- 人只在 `result.md` 里补**两句话**：总体结论 + 异常观察（见该文件）。
- **若 RESULTS.md 内存列为空**（板端采样器键名与预期不同）：回传任一组 `run_report.json` 里的 `memory.raw_keys`，据此修 `run_report` 的键映射后重跑 `run_eval`（板端不用重跑）。
- **不要**回传：音频、完整 worker.log、完整模型原始输出、绝对路径、完整 harness 目录。

## 判定标准（本轮通过条件）

1. **5 组 `timing.status=succeeded`**（跑通到 compat_export）、`stages_detail.enrichment.status=succeeded`；个别 enrichment failed 但主流程未中断也可接受——run_report 已带 error，RESULTS.md 会自动摊出，无需人工找。
2. RESULTS.md 的 enrichment 列 **kw/qa/quote/dec/outline 跨会稳定非空**（重点 decisions/outline 在不同题材会上是否都产得出）。
3. 每组 `run_report.server.loaded_once=true`（单个 `rkllm_server.log` + 单个 `llm_cmd.json` + `ready_seconds` 单值）——证明 enrichment 复用了 server、没二次加载模型（**本轮核心目标**）。如需强证，回传该组 `runtime/memory_samples.jsonl` 数 `llm_server_start` 相位应=1。
4. 得到 **5 个耗时/内存数据点**（按时长对齐），作为板端 4B 首批实机数据。

> 说明：本轮为随机抽样的中等长度会议，验证接线正确性 + server 单次加载 + 跨会产出稳定性 + 首批性能点；**1–2h 长会卖点仍未覆盖**，留待后续单独任务。

## 安全约束

- 不删失败会议证据；不上公共云；命令无感叹号且单次 ≤3 条。

---

## 执行状态（中转机执行后填写，并把本文件移入 `done/`）

- **executed_at**：
- **使用板端地址**：
- **结果目录**：`ops/board-results/2026-09-02_003_enrichment-wire-board-verify/`
- **结论（一句话）**：
- **状态**：⬜ pending / ⬜ done / ⬜ blocked（阻塞原因：）
