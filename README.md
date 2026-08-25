# RK1828 本地会议助手主线

这是从 `D:\Meeting_Agent_fresh` 复制并验证的干净项目主线，集中保存 Windows 前端、Windows Gateway、RK1828 Board Agent/Worker 和 Harness 核心源码。

## 目录

| 路径 | 内容 |
|---|---|
| `src/meeting_agent/` | Harness、阶段、LLM、结构化日志、契约、存储和 Board/Gateway adapters |
| `frontend/meeting-agent-ui-v1/` | React + TypeScript + Vite 前端源码 |
| `schemas/` | Meeting、Transcript、Summary、Result 和 Observability Schema |
| `prompts/` | 当前会议 Prompt 资产 |
| `tests/` | 新主线 unit、contract、integration 和 fixtures |
| `snapshots/board_sync_20260820/` | 只读部署来源快照，不作为当前运行入口 |
| `runtime/` | 新主线运行脚手架，不包含旧会议数据 |

## Python 入口

```text
python -m meeting_agent.harness.main
python -m meeting_agent.cli.harness
meeting-agent-board-agent
meeting-agent-gateway
```

## 前端

```text
frontend/meeting-agent-ui-v1
```

`node_modules/`、`dist/` 和 `.vite/` 未复制。依赖由 `package-lock.json` 管理。

## 边界

- 旧兼容源码和历史归档位于 `D:\Meeting_Agent_legacy`。
- 完整回滚基线位于 `D:\Meeting_Agent_fresh`。
- 原有会议音频、SQLite、失败证据和运行日志没有复制或移动。
- 当前目录拆分不代表 RK1828 部署入口已经切换，也不代表真实会议链路已重新验证。
