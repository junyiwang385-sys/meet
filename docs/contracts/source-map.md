# Source and contract map

## 当前主线

```text
D:\Meeting_Agent_mainline\src\meeting_agent\
D:\Meeting_Agent_mainline\frontend\meeting-agent-ui-v1\
D:\Meeting_Agent_mainline\schemas\
```

Python 包按 Harness、stages、LLM、observability、contracts、storage、Board/Gateway adapters 和 CLI 分层。

## 旧入口与回滚来源

```text
D:\Meeting_Agent_legacy\scripts\
D:\Meeting_Agent_legacy\board_sync_20260820\
D:\Meeting_Agent_legacy\archive\
D:\Meeting_Agent_fresh\              完整过渡与回滚基线
```

主线中的 `snapshots/board_sync_20260820/` 仅用于来源追溯，不是运行入口。

## 运行数据

原有会议音频、SQLite、失败证据和日志继续位于 `D:\Meeting_Agent_fresh\runtime` 与 `output`，本次拆分未复制或修改。

## Contract groups

| Group | Location | Purpose |
|---|---|---|
| Meeting | `schemas/meeting/` | Meeting/chapter structures |
| Transcript | `schemas/transcript/` | Canonical transcript turns |
| Summary | `schemas/summary/` | Meeting minutes summary |
| Result | `schemas/result/` | Harness result and diagnostics projection |
| Observability | `schemas/observability/` | Run manifest, events, metrics and error report |
