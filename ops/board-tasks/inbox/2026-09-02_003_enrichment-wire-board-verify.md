# 任务单：enrichment 接入主链路 + 板端 4B 实机验证

- **task_id**：2026-09-02_003
- **创建**：开发端（本机）
- **目的**：本轮把 **enrichment（关键词/问答/金句/决策/层级大纲）接进 harness 主链路**，并让它**复用摘要 stage 已启动的同一个 rkllm server**（不二次加载模型）。请板端验证：①全链路跑通到导出 + 产出 `enrichment.json`；②server **只加载一次**；③出耗时/内存数（4B 实机）。
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
- [ ] 备好 **1 段非敏感音频，~40min**（本轮就跑这一组；1–2h 长会卖点留待后续单独任务）

## 中转机步骤（`D:\Meeting_Agent_mainline`，PowerShell）

```powershell
git pull
scp -r .\src\meeting_agent <board>:/userdata/meeting_agent1/mainline_v2/src/meeting_agent
# 板端跑完后逐组回传（只回小体积文本，见"回传要求"）：
scp -r <board>:/userdata/.../enrich_verify <本地>\enrich_verify
$env:PYTHONPATH="src"; python -m meeting_agent.observability.run_report <本地>\enrich_verify\g1\harness
```

## 板端步骤（`/userdata/meeting_agent`，≤3 条，无感叹号）

只跑 1 组（~40min 音频）：

```bash
cd /userdata/meeting_agent && PYTHONPATH=/userdata/meeting_agent1/mainline_v2/src python -m meeting_agent.harness.main --source-audio input/<音频>.wav --out-dir output/enrich_verify/g1/harness --overwrite
ls -l output/enrich_verify/g1/harness/03_llm_summary output/enrich_verify/g1/harness/03_llm_summary/enrichment.json
grep -c "rkllm3-server" output/enrich_verify/g1/harness/03_llm_summary/rkllm_server.log
```

（enrichment 默认开；如需关闭对照加 `--no-enrichment`。）

## 期望产物（板端路径）

```text
output/enrich_verify/g1/harness/03_llm_summary/enrichment.json        ← 本轮新产物
output/enrich_verify/g1/harness/meeting_result.json                    ← runtime.stages 含 enrichment
output/enrich_verify/g1/harness/stage_status.json                      ← enrichment stage = succeeded
output/enrich_verify/g1/harness/runtime/memory_summary.json            ← 峰值内存
output/enrich_verify/g1/harness/03_llm_summary/rkllm_server.log        ← 确认 server 只启一次
```

## 回传要求（中转机 → 仓库）

- 写入 `ops/board-results/2026-09-02_003_enrichment-wire-board-verify/result.md`，含：
  - **是否跑通到导出**（exit code）+ `stage_status.json` 里 `enrichment` 的 status；
  - **enrichment.json** 本体（小，可全回）——看 keywords/qa/quotes/decisions/outline_summary 是否有内容、金句是否 `verbatim=true`；
  - **server 只加载一次的证据**：`rkllm_server.log` 只有一次 ready / 一个 startup（贴该行）；
  - **耗时**：`meeting_result.json` 的 `runtime.total_elapsed_seconds`，以及 `runtime.stages` 里 `llm_summary` vs `enrichment` 各自 `elapsed_seconds`；
  - **内存**：`memory_summary.json` 的 `board_used_peak_mb` / `server_rss_peak_mb`；
  - **run_report.json** 的 flags（红旗）+ block/章数。
- **不要**回传：音频、完整 worker.log、完整模型原始输出、绝对路径。

## 判定标准（本轮通过条件）

1. 这 1 组（~40min）**跑通到 compat_export**，`enrichment` stage = succeeded（或 failed 但主流程未中断——failed 也要贴 error）。
2. `enrichment.json` 五类内容**非空**（重点看 decisions/outline_summary 在 40min 会上稳不稳）。
3. `rkllm_server.log` **只启一次**——证明 enrichment 复用了 server、没二次加载模型（本轮核心目标）。
4. 记录这一组的耗时（llm_summary vs enrichment 分开）+ 峰值内存，作为板端 4B 首个实机数据点。

> 说明：40min 属中等长度，可验证接线正确性 + server 单次加载 + 出首个耗时/内存点；**1–2h 长会卖点仍未覆盖**，留待后续单独任务。

## 安全约束

- 不删失败会议证据；不上公共云；命令无感叹号且单次 ≤3 条。

---

## 执行状态（中转机执行后填写，并把本文件移入 `done/`）

- **executed_at**：
- **使用板端地址**：
- **结果目录**：`ops/board-results/2026-09-02_003_enrichment-wire-board-verify/`
- **结论（一句话）**：
- **状态**：⬜ pending / ⬜ done / ⬜ blocked（阻塞原因：）
