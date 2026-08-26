# 任务单：全链路回归（最新完整 build）+ 聚合报告

- **task_id**：2026-08-27_001
- **创建**：开发端（本机）
- **目的**：**直接全链路**跑最新 build，验证累计的**域无关改动**是否改善「过切 / 摘要 / 时间」，
  并生成聚合报告与上次基线对比。**跳过局部测试**（本机单测已 88 全绿）。
- **本次板端地址**：待中转机确认（历史 `10.10.22.26/32/36`，以当前确认为准）
- **目标 commit**：`57075e2`（含以下累计改动，相对上次板端跑的 `5b33a1f`）：
  - segmentation.v2：内聚度深谷检测，speaker 降为弱助推（治过切）
  - think 分 kind：抽取类 `/no_think`（治时间+截断）
  - per-kind 输出预留、自适应 overview 接地门槛加宽、章节质量门
  - 带反馈重试（回显上次输出 + 实测字数）
  - run_report 聚合报告工具

## 前置检查（中转机先确认）

- [ ] `D:\Meeting_Agent_mainline` 已 `git pull` 到 `57075e2`
- [ ] 板端 SSH 连通（地址已确认）
- [ ] 用**同一段非敏感音频**（与上次 `task-f1889c21c947` 一致最好，便于对照）
- [ ] 板端资产就位（ASR / LLM v104 16k / rkllm3-server / 3D-Speaker）

## 中转机步骤（`D:\Meeting_Agent_mainline`，PowerShell）

```powershell
git pull
# 同步更新后的包到板端
scp -r .\src\meeting_agent  <board>:/userdata/meeting_agent1/mainline_v2/src/meeting_agent
# —— 板端执行完后 ——
# 1) 拉回完整 out-dir（本地留存/逐块复盘）
scp -r <board>:/userdata/.../full_v2_regression  <本地>\full_v2_regression
# 2) 生成聚合报告
$env:PYTHONPATH="src"; python -m meeting_agent.observability.run_report <本地>\full_v2_regression\harness
```

> 用**新 out-dir + `--overwrite`**（不 resume），避免旧 build 的缓存干扰对照。

## 板端步骤（`/userdata/meeting_agent`，≤3 条，无感叹号）

```bash
cd /userdata/meeting_agent && PYTHONPATH=/userdata/meeting_agent1/mainline_v2/src python -m meeting_agent.harness.main --source-audio input/<同上次音频>.wav --out-dir output/full_v2_regression/harness --overwrite
ls -l output/full_v2_regression/harness output/full_v2_regression/harness/03_llm_summary
```

## 对照基线（上次 `5b33a1f`，来自 run_report）

| 指标 | 上次基线 | 本次期望方向 |
|---|---|---|
| block_count / chapter_count | 37 / 26 | **↓**（seg.v2 减少 speaker 假边界） |
| 换人开启的块 | 35 / 37 | **↓↓**（假边界应大幅消失） |
| 块摘要均字数 | 84.5 | ↑（think-off 释放预算） |
| overview_source / 字数 | (None=章节归并) / 197 | **source_timeline** / ↑ |
| llm_summary 时延 | 619 s | **↓↓**（关 think） |
| thinking（block/full/speaker） | 816/1258/752 字 | **≈0**（已 /no_think） |
| 重试率 | 22%（11/51） | ↓ |
| finish_reason length | 1 次 | 0 |
| chars_per_token 实测 | 1.689 | 记录（供校准 1.3） |
| 空字段 | 5 个 | 不变（域相关，本次不动） |

## 回传要求（中转机 → 仓库）

放入 `ops/board-results/2026-08-27_001_full-chain-regression/`：

- **`run_report.md` 和 `run_report.json`**（纯聚合指标，安全；跨轮对比主载体）
- `result.md`：一句话结论 + 上表实际值 + 是否达到期望方向
- 小体积附件：`plan.json`、`segmentation.json`、`stage_status.json`、`run_metrics.json`

**不要回传**：音频、完整 `logs/`、`03_llm_summary/blocks|requests/` 下的完整 prompt/响应、绝对路径。完整 `harness/` 只在 PC 本地留存。

## 安全约束

- 非敏感音频；不删失败证据；不上公共云；板端命令 ≤3 条、无感叹号。
- 表述纪律：跑通≠质量达标；质量以 run_report 指标为准。

---

## 执行状态（中转机执行后填写，并把本文件移入 `done/`）

- **executed_at**：
- **使用板端地址**：
- **结果目录**：`ops/board-results/2026-08-27_001_full-chain-regression/`
- **结论（一句话）**：
- **状态**：⬜ pending / ⬜ done / ⬜ blocked（阻塞原因：）
