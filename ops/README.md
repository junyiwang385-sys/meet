# 开发协作流程（GitHub 作为任务总线）

> 生效日期：2026-08-26
> 适用仓库：`junyiwang385-sys/meet`（GitHub），分支 `main`

## 1. 角色与机器

| 角色 | 机器 | 职责 |
|---|---|---|
| **开发端** | 本机（`C:\Users\Admin\meet`） | 写代码、生成板端任务单、`git push`。不联网装依赖、不直接碰板端。 |
| **执行端（中转机）** | mainline 机（`D:\Meeting_Agent_mainline`） | `git pull` → 本地验证 → **SSH 到 RK1828 板端**执行 → 回传小体积结果 → `git push`。 |
| **板端** | RK1828（`/userdata/meeting_agent`） | 被中转机 SSH 驱动，跑真实处理脚本。 |
| **总线** | GitHub `main` 分支 | 任务单下行、结果上行。 |

**前置条件**：mainline 机上的 `D:\Meeting_Agent_mainline` 必须是本仓库的 clone（tracking 同一 GitHub remote），否则总线不成立。

## 2. 目录约定（仓库即消息队列）

```text
ops/
  README.md                 # 本流程
  board-tasks/
    task-template.md        # 任务单模板
    inbox/                  # 本机→中转机:待执行任务单（开发端写）
    done/                   # 执行完成后由中转机移入并标状态
  board-results/            # 中转机→本机:小体积诊断结果回传（一任务一子目录）
```

## 3. 闭环流程

1. **开发端（本机）**：按模板写任务单到 `ops/board-tasks/inbox/`，命名 `YYYY-MM-DD_NNN_<slug>.md` → commit → **push（由本机执行）**。
2. **执行端（mainline 机）**：`git pull` → 读 inbox 任务单 → 先跑「中转机步骤」→ 再 SSH 跑「板端步骤」→ 把结果写入 `ops/board-results/<同名>/` → 把任务单从 `inbox/` 移到 `done/` 并在文件末尾填「执行状态」→ commit → push。
3. **开发端（本机）**：`git pull` → 读 `board-results/` → 决策下一步。

## 4. 两条硬规矩

### 4.1 只回传小体积文本
- 允许进 GitHub：sidecar JSON（`error_report.json` 等）、日志**摘录**、exit code、`meeting_result.json` 的**诊断字段子集**。
- **禁止进 GitHub**：真实会议音频、完整模型输出、完整 `worker.log`、大产物、绝对路径与私有日志片段。音频不上公共云是铁约束，`.gitignore` 已排除 `runtime/`、`output/`。

### 4.2 板端操作纪律（对齐任务交接约束）
- 单次 ≤ 3 条命令；**命令中不得出现感叹号**。
- 优先直接跑板端脚本，不绕回 Windows 伪执行。
- 不删除真实失败会议的音频、结果、诊断、错误证据。
- 板端 IP 历史出现过 `10.10.22.26/32/36`，**每次以当前确认地址为准**，任务单里必须写明本次使用地址（或标注“待中转机确认”）。

### 4.3 表述纪律
- “本地合成验证通过” ≠ “真实会议处理完成”。
- “源码接入完成” ≠ “浏览器/板端已验证”。
- 探针、合成测试、真实链路分开表述。

## 5. 命名与状态

- 任务单：`ops/board-tasks/inbox/2026-08-26_001_gateway-diagnostics-check.md`
- 结果目录：`ops/board-results/2026-08-26_001_gateway-diagnostics-check/`（内含 `result.md` + 小体积附件）
- 完成后任务单移至 `ops/board-tasks/done/`，末尾「执行状态」记录：executed_at / 使用的板端地址 / 结果目录 / 结论一句话。
