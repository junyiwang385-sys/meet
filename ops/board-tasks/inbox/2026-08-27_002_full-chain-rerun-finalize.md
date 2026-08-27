# 任务单：全链路重跑（cfc8557）+ finalize 实机验证

- **task_id**：2026-08-27_002
- **创建**：开发端（本机）
- **目的**：上一轮 001（`5b33a1f`-era 后的某 build）全链路**失败于 speaker-batch**，已修复；本轮
  ①全链路重跑验证能**跑通到导出** + 出聚合报告；②验证**新实现的 Gateway finalize** 实机可用。
- **目标 commit**：`cfc8557`
- **本次板端地址**：待中转机确认（历史 `10.10.22.26/32/36`）

## 相对 001 的新增改动

- **speaker 修复**（001 失败主因）：best-effort 不 raise（缺 speaker 跳过不拖垮 pipeline）、refs 由代码从该 speaker 自己最长段指派（杜绝编造 refs 截断）、过滤 unknown 与 <80 字琐碎 speaker。
- **unknown 顺延**：backend `display.py` + 前端 `transcriptRows` 各自把 unknown 归并到相邻已知说话人。
- **前端**：处理页不确定进度动画 + 已用时跳秒；review 页能力不可用时禁用按钮+原因。前端 `npm run build` 已本机通过（node_modules 已装）。
- **Gateway finalize（新）**：`POST /finalize`、`GET /exports`、`GET /exports/{format}`；从编辑后 draft 渲染 HTML/TXT/JSON；`GATEWAY_CAPABILITIES.finalize=True`。

## 前置检查

- [ ] `D:\Meeting_Agent_mainline` 已 `git pull` 到 `cfc8557`
- [ ] 板端 SSH 连通（地址已确认）
- [ ] 用**与 001 同一段非敏感音频**便于对照
- [ ] **重启 Gateway 让 finalize 新代码生效**；前端 `npm run build`

## A. 全链路重跑（板端 harness）

**中转机步骤（PowerShell）：**

```powershell
git pull
scp -r .\src\meeting_agent  <board>:/userdata/meeting_agent1/mainline_v2/src/meeting_agent
# 板端跑完后：
scp -r <board>:/userdata/.../full_v2_rerun  <本地>\full_v2_rerun
$env:PYTHONPATH="src"; python -m meeting_agent.observability.run_report <本地>\full_v2_rerun\harness
```

**板端步骤（≤3 条，无感叹号）：**

```bash
cd /userdata/meeting_agent && PYTHONPATH=/userdata/meeting_agent1/mainline_v2/src python -m meeting_agent.harness.main --source-audio input/<同001音频>.wav --out-dir output/full_v2_rerun/harness --overwrite
ls -l output/full_v2_rerun/harness output/full_v2_rerun/harness/03_llm_summary
```

**对照基线（001 失败run 的 run_report）与本轮期望：**

| 指标 | 001（失败） | 本轮期望 |
|---|---|---|
| 结果状态 | **failed@speaker-batch** | **succeeded 到导出** |
| block_count / chapter_count | 8 / 7 | 8 左右（seg.v2 已生效） |
| thinking（block/full/speaker） | 0 / 0 / 0 | 仍 ≈0（/no_think） |
| speaker 摘要 | 报缺4人→失败 | best-effort，产出若干，**不失败** |
| 块摘要均字数 | 73.5 | 记录（域相关，暂不调） |
| chars_per_token 实测 | 1.528 | 记录（供校准 1.3） |

## B. Gateway finalize 实机验证（前端 → Gateway）

前端走一遍：处理到 `review_ready` → 编辑草稿 → **确认纪要** → 观察：

- [ ] `POST /api/meetings/{id}/finalize` 返回 200（非 404），`state=finalized`
- [ ] `GET /api/meetings/{id}/exports` 列出 html/txt/json 三项 `state=ready`
- [ ] 三个 `GET /exports/{format}` 可下载，内容正确（HTML 可打开、TXT 可读、JSON 可解析）
- [ ] 正式版反映**草稿编辑后**的内容（方案 A）

板端/中转机对应目录应出现：`<会议目录>/exports/formal_minutes.html|.txt`、`formal_result.json`、`manifest.json`。

## 回传要求

放入 `ops/board-results/2026-08-27_002_full-chain-rerun-finalize/`：

- **`run_report.md` / `run_report.json`**（聚合指标，安全）
- `result.md`：全链路是否跑通到导出 + 上表实际值；finalize 四个勾是否通过；一句话结论
- 小体积附件：`plan.json`、`segmentation.json`、`stage_status.json`、`run_metrics.json`
- finalize 侧：`exports/manifest.json`（可回传，无敏感原文）

**不要回传**：音频、完整 logs、`blocks|requests/` 完整 prompt/响应、`formal_minutes.*` 正式版全文（含会议内容）、绝对路径。

## 安全约束

- 非敏感音频；不删失败证据；不上公共云；板端命令 ≤3 条、无感叹号。

---

## 执行状态（中转机执行后填写，并把本文件移入 `done/`）

- **executed_at**：
- **使用板端地址**：
- **A 全链路**：⬜ 跑通到导出 / ⬜ 仍失败（阶段：）
- **B finalize**：⬜ 四项通过 / ⬜ 部分（说明：）
- **结果目录**：`ops/board-results/2026-08-27_002_full-chain-rerun-finalize/`
- **状态**：⬜ pending / ⬜ done / ⬜ blocked
