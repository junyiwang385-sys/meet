# 任务单：mainline v25 短 WAV 板端回归（验证 deterministic_blocks_map_reduce）

- **task_id**：2026-08-26_001
- **创建**：开发端（本机）
- **目的**：用**非敏感短 WAV**在板端端到端跑一遍 mainline（含纪要改造 v25 新路径），验证
  A→B→C→D 分块 map-reduce 能真实跑通，并回传 `plan.json`/`segmentation.json` 等**小体积**诊断，
  用真实数据评估新提示词在 Qwen3-4B int4 下的切块数、章节数、摘要字数、retry/too_short 计数。
- **本次板端地址**：待中转机确认（历史 `10.10.22.26/32/36`，以当前确认为准）
- **关联 commit**：`5b33a1f`（product-summary.v25，纪要改造 P2-P5）

## 前置检查（中转机先确认）

- [ ] `D:\Meeting_Agent_mainline` 已 `git pull` 到 `5b33a1f`
- [ ] 板端 SSH 连通（地址已确认）
- [ ] 板端有**非敏感演示短 WAV**（放 `/userdata/meeting_agent/input/`，本单以 `demo_short.wav` 为例）
- [ ] 板端资产就位：ASR 模型 `models/asr/qwen3-asr-0.6b-rknn`、LLM `models/llm/v104/qwen3-4b-v104-ctx16k`、
      `/usr/bin/rkllm3-server`、3D-Speaker 环境、board 脚本 `/userdata/meeting_agent/scripts`

## 中转机步骤（`D:\Meeting_Agent_mainline`，PowerShell）

```powershell
git pull
# 把更新后的 python 包同步到板端（目标路径待确认，示例用 mainline_v25/src）
scp -r .\src\meeting_agent  <board>:/userdata/meeting_agent/mainline_v25/src/meeting_agent
```

> 说明：板端用 `python -m meeting_agent.harness.main` 运行，需要 `meeting_agent` 可导入，
> 故把 mainline 的 `src/meeting_agent` 同步到板端 `mainline_v25/src` 并用 PYTHONPATH 指向它。
> board 脚本 / 模型 / rkllm3-server 已在板端，不随本单同步。若板端已有安装方式（pip -e），
> 可改用既有方式，路径以中转机现场为准。

## 板端步骤（`/userdata/meeting_agent`，≤3 条，无感叹号）

```bash
cd /userdata/meeting_agent && PYTHONPATH=/userdata/meeting_agent/mainline_v25/src python -m meeting_agent.harness.main --source-audio input/demo_short.wav --out-dir output/mainline_v25_regression --overwrite
ls -l output/mainline_v25_regression output/mainline_v25_regression/03_llm_summary
```

## 期望产物（板端路径，`out-dir = output/mainline_v25_regression`）

```text
03_llm_summary/plan.json          # policy 应为 deterministic_blocks_map_reduce；block_count/chapter_count/segmentation
03_llm_summary/segmentation.json  # blocks + boundary_reason_counts（gap/speaker/cohesion/budget_split 分布）
03_llm_summary/chapters.json      # 合并后的章节
meeting_summary.json              # 最终纪要（非敏感 demo）
run_metrics.json                  # llm 计数：request_count/retry_count/split_count/validation_failed_count/reused_request_count
stage_status.json                 # 各阶段状态
error_report.json                 # 若失败
```

## 回传要求（中转机 → 仓库）

把上面**小体积 JSON** scp 回中转机，放入 `ops/board-results/2026-08-26_001_mainline-v25-short-wav-regression/`，
并写 `result.md` 记录：

- harness 退出码
- `plan.json` 的 `policy` / `block_count` / `chapter_count` / `segmentation.boundary_reason_counts`
- `run_metrics.json` 的 llm 计数（尤其 `retry_count`，用于看 too_short 重试是否频繁触发）
- 各章节 `overview` 字数（判断"摘要字数少"是否改善）
- 一句话结论：新路径是否跑通、质量主观感受

**不要回传**：`demo_short.wav` 音频、完整 `logs/`、完整模型输出、`03_llm_summary/blocks/` 与 `requests/` 目录下的完整 prompt/响应、绝对路径。

## 安全约束

- 只用非敏感演示 WAV；不删失败会议证据；不上公共云。
- 板端命令单次 ≤3 条、无感叹号。
- 表述纪律：短 WAV 探针**不等于**生产链路完成；跑通≠质量达标，质量以回传数据为准。

---

## 执行状态（中转机执行后填写，并把本文件移入 `done/`）

- **executed_at**：
- **使用板端地址**：
- **结果目录**：`ops/board-results/2026-08-26_001_mainline-v25-short-wav-regression/`
- **结论（一句话）**：
- **状态**：⬜ pending / ⬜ done / ⬜ blocked（阻塞原因：）
