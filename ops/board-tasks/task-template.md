# 任务单：<简短标题>

- **task_id**：2026-08-26_001
- **创建**：开发端（本机）
- **目的**：<一句话说明这次要板端配合验证/产出什么>
- **本次板端地址**：<10.10.22.xx  或  待中转机确认>
- **关联**：<关联的 commit / 文档 / 上一任务，可选>

## 前置检查（中转机先确认）

- [ ] `D:\Meeting_Agent_mainline` 已 `git pull` 到最新
- [ ] 板端可 SSH 连通（地址已确认）
- [ ] <其它前置，如某模型/脚本存在>

## 中转机步骤（`D:\Meeting_Agent_mainline`，PowerShell）

```powershell
# 本地验证/准备命令，如构建、同步文件到板端等
```

## 板端步骤（`/userdata/meeting_agent`，≤3 条，无感叹号）

```bash
# 命令1
# 命令2
# 命令3
```

## 期望产物（板端路径）

```text
<例如 /userdata/meeting_agent/output/.../error_report.json>
```

## 回传要求（中转机 → 仓库）

- 写入 `ops/board-results/<与任务同名>/result.md`
- 附带**小体积**文本：sidecar JSON、日志摘录、exit code
- **不要**回传：音频、完整模型输出、完整 worker.log、绝对路径

## 安全约束

- 不删失败会议证据；不上公共云；命令无感叹号且单次 ≤3 条。

---

## 执行状态（中转机执行后填写，并把本文件移入 `done/`）

- **executed_at**：
- **使用板端地址**：
- **结果目录**：`ops/board-results/<...>/`
- **结论（一句话）**：
- **状态**：⬜ pending / ⬜ done / ⬜ blocked（阻塞原因：）
