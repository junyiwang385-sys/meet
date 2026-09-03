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
- **不涉及**：diar/ASR 板端脚本、模型、老 `prompts/*_zh.txt`（死层，勿动）。

## 前置检查（中转机先确认）

- [ ] `D:\Meeting_Agent_mainline` 已 `git pull` 到本次 push 的 `feature/transcript-postprocess`
- [ ] 板端 SSH 连通（地址已确认）
- [ ] 从音频库**随机抽 5 段非敏感会议**（g1–g5，长度不限，记录各自时长）；1–2h 长会卖点留待后续单独任务

## 中转机步骤（`D:\Meeting_Agent_mainline`，PowerShell）

```powershell
git pull
scp -r .\src\meeting_agent <board>:/userdata/meeting_agent1/mainline_v2/src/meeting_agent
# 板端跑完后逐组回传（只回小体积文本，见"回传要求"）：
scp -r <board>:/userdata/.../enrich_verify <本地>\enrich_verify
$env:PYTHONPATH="src"; python -m meeting_agent.observability.run_report <本地>\enrich_verify\g1\harness
```

## 板端步骤（`/userdata/meeting_agent`，≤3 条，无感叹号）

先把随机抽的 5 段文件名填进 `A`，循环跑（各 `--overwrite`）：

```bash
cd /userdata/meeting_agent && A="a1.wav a2.wav a3.wav a4.wav a5.wav"; i=0; for f in $A; do i=$((i+1)); PYTHONPATH=/userdata/meeting_agent1/mainline_v2/src python -m meeting_agent.harness.main --source-audio input/$f --out-dir output/enrich_verify/g$i/harness --overwrite; done
for i in 1 2 3 4 5; do echo "== g$i =="; grep -c rkllm3-server output/enrich_verify/g$i/harness/03_llm_summary/rkllm_server.log; done
ls -l output/enrich_verify/g*/harness/03_llm_summary/enrichment.json
```

（enrichment 默认开；如需关闭对照加 `--no-enrichment`。）

## 期望产物（板端路径，每组 g1–g5）

```text
output/enrich_verify/gN/harness/03_llm_summary/enrichment.json        ← 本轮新产物
output/enrich_verify/gN/harness/meeting_result.json                    ← runtime.stages 含 enrichment + duration_ms
output/enrich_verify/gN/harness/stage_status.json                      ← enrichment stage = succeeded
output/enrich_verify/gN/harness/runtime/memory_summary.json            ← 峰值内存
output/enrich_verify/gN/harness/03_llm_summary/rkllm_server.log        ← 确认 server 只启一次
```

## 回传要求（中转机 → 仓库）

- 写入 `ops/board-results/2026-09-02_003_enrichment-wire-board-verify/result.md`（**已备好骨架，逐组回填**），含：
  - **汇总表**（5 组一行一组）：时长 / 是否跑通 / enrichment stage / 五类计数 / server 启动次数 / 总耗时 / llm_summary 耗时 / enrichment 耗时 / 峰值内存；
  - **每组**：`stage_status.json` 里 `enrichment` 的 status（failed 也贴 error）、`enrichment.json` 本体（小，可全回）、`rkllm_server.log` 的 ready 行、`meeting_result.json` 的 `duration_ms` + 各 stage `elapsed_seconds`、`memory_summary.json` 峰值、`run_report.json` 的 flags + block/章数。
- **不要**回传：音频、完整 worker.log、完整模型原始输出、绝对路径。

## 判定标准（本轮通过条件）

1. **5 组都跑通到 compat_export**，`enrichment` stage = succeeded（个别 failed 但主流程未中断也可接受——必须贴 error 说明原因）。
2. `enrichment.json` 五类内容**跨会稳定非空**（重点看 decisions/outline_summary 在不同题材会上是否都产得出）。
3. 每组 `rkllm_server.log` **只启一次**——证明 enrichment 复用了 server、没二次加载模型（本轮核心目标）。
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
