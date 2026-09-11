# 极米离线纪要助手 API 接口契约 v1.0

| 项目 | 内容 |
| --- | --- |
| 文档状态 | 正式前端开发前的接口基线 |
| 文档版本 | 1.0 |
| 日期 | 2026-08-19 |
| 前端范围 | 当前需求调研目录中的会议库、录音、处理、核对、回放、设置和存储 UI |
| 前端访问地址 | `http://127.0.0.1:8787` |
| 当前 Gateway 基线 | `meeting-agent-gateway-v0 0.2.0` |
| 当前板端协议 | `board-agent.v1` |
| 当前板端 Agent | `0.2.0` |
| 当前会议处理任务 | `harness_meeting_v0` |
| 当前模型配置 | `qwen3-4b-v104-ctx16k` |

---

## 1. 文档目标

本接口契约用于连接以下三部分：

```text
React + TypeScript 正式前端
  → Windows PC Gateway
  → RK1828 Board Agent 与本地 Harness
```

接口覆盖当前 UI 已确定的完整产品流程：

```text
会议库
  → 新建会议
       → 本地音频
       → PC 录音
       → 板端录音
  → 上传或结束录音
  → 板端处理
       → 先开放全文和发言人
       → 后台继续生成纪要、章节、决策和待办
  → 人工核对与保存草稿
  → 确认正式版本
  → HTML / TXT / JSON
  → 可单独删除原始音频
```

本契约的核心目标：

1. 前端只访问 PC Gateway，不直接访问 RK1828。
2. 高频状态查询与完整结果读取分离。
3. 支持“全文已经可用，但纪要仍在生成”的部分结果状态。
4. 支持历史会议持久化、搜索、筛选和恢复。
5. 支持失败后按范围重试，而不是一律重新上传音频。
6. 支持草稿、正式确认、导出和原始音频独立删除。
7. 不自动补造责任人、截止时间、身份或证据。
8. 音频、转写、说话人、纪要和正式版本均在本地及局域网内处理，不上传公共云。

---

## 2. 当前实现与目标接口的关系

### 2.1 当前已实现接口

当前 Gateway `0.2.0` 已实现：

```text
GET  /api/info
GET  /api/board/health
POST /api/meetings
GET  /api/meetings/{meeting_id}
PUT  /api/meetings/{meeting_id}/audio
POST /api/meetings/{meeting_id}/cancel
GET  /api/meetings/{meeting_id}/result
```

当前 Board Agent `0.2.0` 已实现：

```text
GET  /v1/health
POST /v1/tasks
GET  /v1/tasks/{task_id}
PUT  /v1/tasks/{task_id}/audio
POST /v1/tasks/{task_id}/cancel
GET  /v1/tasks/{task_id}/result
```

### 2.2 当前实现的限制

| 项目 | 当前状态 | v1.0 目标 |
| --- | --- | --- |
| 会议数量 | Gateway 内存中仅保存一个 `_current_meeting` | SQLite 持久化多个历史会议 |
| Gateway 重启 | 当前会议映射丢失 | 会议库和状态可恢复 |
| 上传格式 | 板端仅接受 WAV | Gateway 接受多种本地格式并在 PC 本地转换 |
| 上传恢复 | 不支持断点续传 | 网络中断后从头重试完整传输 |
| 结果可用时间 | `meeting_result.json` 完成后才读取 | 转写完成后先返回全文和发言人 |
| 草稿 | 未实现 | 本地持久化草稿和修订号 |
| 正式确认 | 未实现 | 生成 HTML、TXT、JSON |
| 原始音频删除 | 未实现 | 确认后允许单独删除 |
| PC 录音 | UI 模拟 | 浏览器 MediaRecorder 后上传 Gateway |
| 板端录音 | UI 模拟 | Gateway 代理 Board Agent 录音接口 |
| 存储管理 | UI 模拟 | 真实空间统计、临时文件清理和音频删除 |

### 2.3 兼容原则

正式接口继续使用 `/api` 前缀，保留当前已经验证的路径。成功响应不额外包裹 `data` 字段，错误继续使用统一的 `error` 对象。

正式前端不再发送 `task_kind`。Gateway 内部固定将正式会议处理映射为：

```text
harness_meeting_v0
```

`audio_upload_probe` 和 `transport_probe` 只保留在调试页面或自动测试中，不进入正式 UI。

---

## 3. 架构与职责边界

### 3.1 浏览器前端

负责：

- 页面与路由。
- 本地文件选择。
- PC 麦克风授权和 MediaRecorder 录音。
- 上传进度展示。
- 状态轮询。
- 结果展示、编辑和草稿提交。
- 播放控制、搜索和证据跳转。
- 由机器状态映射中文提示文案。

不负责：

- 直接访问 RK1828。
- 直接操作任意本地文件路径。
- 自行推断板端技术阶段是否成功。
- 自行生成或补造纪要字段。
- 把原始结果直接当作可信正式版本。

### 3.2 Windows PC Gateway

负责：

- 只绑定本机回环地址。
- 为正式前端提供统一 API。
- SQLite 会议库和本地会议目录。
- 接收本地音频和 PC 录音文件。
- 非 WAV 音频的 PC 本地转换。
- 将规范化 WAV 从头发送到 RK1828。
- 将板端阶段映射为产品状态、可用内容和进度。
- 读取并规范化 Harness 结果。
- 保存草稿、正式版本和导出清单。
- 控制原始音频删除和临时文件清理。
- 代理板端录音。

### 3.3 RK1828 Board Agent

负责：

- 健康状态。
- 单活动任务控制。
- 接收规范化 WAV。
- 调用 Harness。
- 回传板端真实阶段。
- 提供部分结果和完整结果。
- 取消任务。
- 板端录音控制。

### 3.4 Harness

负责：

```text
source audio
  → 3D-Speaker / CAM++ 分段
  → Batch Qwen3-ASR
  → canonical transcript / timeline
  → Qwen3-4B 16K 纪要生成
  → compatibility export
```

Gateway 不修改模型生成内容，只做结构规范化、状态映射、用户草稿叠加和正式导出。

---

## 4. 通用 HTTP 约定

### 4.1 Base URL

```text
http://127.0.0.1:8787
```

正式前端应与 Gateway 同源部署。前端不得把板端地址写入业务请求。

### 4.2 Content-Type

| 内容 | Content-Type |
| --- | --- |
| JSON 请求与响应 | `application/json; charset=utf-8` |
| WAV | `audio/wav` 或 `audio/x-wav` |
| MP3 | `audio/mpeg` |
| M4A | `audio/mp4` |
| FLAC | `audio/flac` |
| AAC | `audio/aac` |
| OGG | `audio/ogg` |
| 无法识别的二进制音频 | `application/octet-stream`，同时必须提供文件名 |

### 4.3 时间与时长

- 时间戳统一使用 UTC ISO-8601，例如 `2026-08-19T08:30:00Z`。
- 前端负责转换为本地显示时间。
- 音频时间统一使用整数毫秒 `start_ms`、`end_ms`、`duration_ms`。
- 禁止使用格式化字符串作为唯一时间数据。

### 4.4 标识符

| 标识符 | 格式示例 | 说明 |
| --- | --- | --- |
| `meeting_id` | `meeting-a4b8c91d210f` | Gateway 生成，稳定且可用于目录名 |
| `board_task_id` | `task-5eda41930494` | Board Agent 生成，仅诊断使用 |
| `recording_id` | `recording-12c90a10` | 板端录音会话 |
| `segment_id` | `seg-000284` | 全文片段稳定 ID |
| `speaker_id` | `spk-001` | 发言人稳定 ID |
| `chapter_id` | `chapter-003` | 章节 ID |
| `evidence_id` | `ev-001` | 证据 ID |
| `draft_revision` | `4` | 草稿乐观并发修订号 |
| `result_revision` | `2` | 处理结果修订号 |

`meeting_id` 只允许字母、数字、点、下划线和短横线，长度 1–128。

### 4.5 请求追踪

Gateway 应为每次请求返回：

```text
X-Request-ID: req-xxxxxxxxxxxx
```

错误响应同时在 JSON 中返回 `request_id`。前端只在诊断详情中显示，不作为普通用户提示。

### 4.6 缓存

所有动态 API 默认返回：

```text
Cache-Control: no-store
```

正式 HTML 导出可使用 `no-cache`，但不得被公共代理缓存。

### 4.7 分页

列表接口统一使用：

```text
page=1
page_size=30
```

约束：

```text
1 <= page_size <= 100
```

响应格式：

```json
{
  "items": [],
  "page": 1,
  "page_size": 30,
  "total": 0,
  "has_more": false
}
```

### 4.8 成功状态码

| 状态码 | 用途 |
| --- | --- |
| `200 OK` | 查询、更新、取消、删除或同步操作成功 |
| `201 Created` | 本地会议记录创建成功 |
| `202 Accepted` | 上传后处理、重试、正式导出或录音停止已接受 |
| `204 No Content` | 无响应体的幂等操作 |

### 4.9 错误响应

统一格式：

```json
{
  "error": {
    "code": "SUMMARY_GENERATION_FAILED",
    "message": "纪要生成未完成",
    "phase": "synthesizing",
    "retryable": true,
    "retry_scope": "summary",
    "preserved": {
      "audio": true,
      "transcript": true,
      "speakers": true,
      "summary": false,
      "formal_version": false
    },
    "details": {}
  },
  "request_id": "req-13fb03a02ad8"
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `code` | 是 | 稳定机器错误码 |
| `message` | 是 | 可记录的简短错误描述 |
| `phase` | 否 | 失败发生的产品阶段 |
| `retryable` | 是 | 当前错误是否允许重试 |
| `retry_scope` | 否 | `upload`、`all`、`summary`、`exports` |
| `preserved` | 否 | 失败后仍保留的内容 |
| `details` | 否 | 小型、无敏感内容的诊断数据 |
| `request_id` | 是 | 请求追踪 ID |

前端正式提示文案应按 `error.code` 映射，不直接把底层异常堆栈展示给用户。

---

## 5. 状态模型

### 5.1 MeetingState

```text
created
recording
uploading
processing
review_ready
finalizing
finalized
failed
cancelled
```

| 状态 | 含义 | 是否终态 |
| --- | --- | --- |
| `created` | 会议记录已创建，等待音频或录音 | 否 |
| `recording` | 板端正在录音 | 否 |
| `uploading` | Gateway 正在接收或发送完整音频 | 否 |
| `processing` | 板端正在转写或生成纪要 | 否 |
| `review_ready` | 全部可编辑结果已生成，等待人工核对 | 否 |
| `finalizing` | 正在生成正式版本 | 否 |
| `finalized` | 正式版本已确认并生成 | 是 |
| `failed` | 当前阶段失败，可根据能力决定是否重试 | 是 |
| `cancelled` | 用户取消 | 是 |

`audio_deleted` 不是会议状态。会议确认后删除音频时，会议仍保持 `finalized`，仅 `audio.state` 改为 `deleted`。

### 5.2 MeetingPhase

```text
awaiting_source
recording
uploading
converting
transcribing
synthesizing
exporting
ready
cancelled
```

### 5.3 板端阶段到产品阶段的映射

| Board Agent / Harness 阶段 | 产品阶段 | 正式 UI 文案方向 |
| --- | --- | --- |
| `awaiting_audio` | `awaiting_source` | 等待音频 |
| `audio_upload` | `uploading` | 正在传输音频 |
| `segmentation` | `transcribing` | 正在识别与转写 |
| `batch_asr` | `transcribing` | 正在识别与转写 |
| `transcript_prepare` | `transcribing` | 正在整理全文 |
| `llm_summary` | `synthesizing` | 正在生成纪要、决策和总结 |
| `compat_export` | `synthesizing` | 正在整理会议结果 |
| `meeting_ready` | `ready` | 会议结果已生成 |
| `cancelled` | `cancelled` | 已取消 |

正式 UI 不展开显示完整技术阶段。`raw_stage` 仅供诊断页和日志使用。

### 5.4 ResultAvailability

```json
{
  "transcript": true,
  "speakers": true,
  "minutes": false,
  "chapters": false,
  "decisions": false,
  "action_items": false,
  "evidence": true,
  "formal_version": false
}
```

必须支持以下状态：

```text
state = processing
phase = synthesizing
availability.transcript = true
availability.speakers = true
availability.minutes = false
```

这对应当前 UI 的“转写完成后先展示全文和发言人，纪要继续后台生成”。

### 5.5 MeetingCapabilities

后端返回可执行能力，前端不重复推导业务规则：

```json
{
  "can_cancel": true,
  "can_retry_all": false,
  "can_retry_summary": false,
  "can_edit": false,
  "can_save_draft": false,
  "can_finalize": false,
  "can_play_audio": true,
  "can_delete_audio": false,
  "can_reveal_files": true,
  "can_remove_index": false
}
```

### 5.6 状态流转

#### 本地音频或 PC 录音

```text
created
  → uploading
  → processing/transcribing
  → processing/synthesizing
  → review_ready
  → finalizing
  → finalized
```

#### 板端录音

```text
created
  → recording
  → processing/transcribing
  → processing/synthesizing
  → review_ready
  → finalizing
  → finalized
```

#### 失败与重试

```text
uploading → failed → retry(upload) → uploading
transcribing → failed → retry(all) → processing/transcribing
synthesizing → failed → retry(summary) → processing/synthesizing
finalizing → failed → retry(exports) → finalizing
```

#### 取消

```text
uploading | processing | recording
  → cancelled
```

取消不自动删除 Gateway 已完整保存的原始音频。未完成的 `.part` 文件必须删除。

---

## 6. 核心数据结构

## 6.1 MeetingListItem

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "title": "研发方案评审",
  "source_type": "local_upload",
  "source_label": "本地音频",
  "state": "review_ready",
  "phase": "ready",
  "progress": {
    "percent": 100,
    "estimated": false,
    "elapsed_seconds": 312,
    "estimated_total_seconds": 300
  },
  "availability": {
    "transcript": true,
    "speakers": true,
    "minutes": true,
    "chapters": true,
    "decisions": true,
    "action_items": true,
    "evidence": true,
    "formal_version": false
  },
  "review": {
    "pending_count": 3,
    "reviewed_count": 6,
    "dirty": false
  },
  "audio": {
    "state": "available",
    "duration_ms": 2412000,
    "size_bytes": 509503788
  },
  "meeting_date": "2026-08-18T02:15:00Z",
  "created_at": "2026-08-18T02:15:00Z",
  "updated_at": "2026-08-18T02:20:13Z"
}
```

`source_type` 枚举：

```text
local_upload
pc_record
board_record
```

`audio.state` 枚举：

```text
pending
recording
uploading
converting
available
deleted
missing
unreadable
```

## 6.2 MeetingDetail

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "title": "研发方案评审",
  "language": "zh-CN",
  "source": {
    "type": "local_upload",
    "original_name": "review_meeting.m4a",
    "original_extension": "m4a",
    "mime_type": "audio/mp4",
    "size_bytes": 509503788,
    "sha256": "64-character-lowercase-hex",
    "requires_conversion": true
  },
  "state": "processing",
  "phase": "synthesizing",
  "raw_stage": "llm_summary",
  "seq": 12,
  "progress": {
    "percent": 46,
    "estimated": true,
    "elapsed_seconds": 138,
    "estimated_total_seconds": 300,
    "estimated_remaining_seconds": 162
  },
  "availability": {
    "transcript": true,
    "speakers": true,
    "minutes": false,
    "chapters": false,
    "decisions": false,
    "action_items": false,
    "evidence": true,
    "formal_version": false
  },
  "capabilities": {
    "can_cancel": true,
    "can_retry_all": false,
    "can_retry_summary": false,
    "can_edit": false,
    "can_save_draft": false,
    "can_finalize": false,
    "can_play_audio": true,
    "can_delete_audio": false,
    "can_reveal_files": true,
    "can_remove_index": false
  },
  "audio": {
    "state": "available",
    "duration_ms": 2412000,
    "size_bytes": 509503788,
    "playable": true,
    "deleted_at": null
  },
  "review": {
    "pending_count": 0,
    "reviewed_count": 0,
    "dirty": false,
    "draft_revision": 0
  },
  "exports": [],
  "file_health": {
    "metadata": "available",
    "source_audio": "available",
    "result": "partial",
    "draft": "not_created",
    "formal_html": "not_created",
    "formal_txt": "not_created",
    "formal_json": "not_created"
  },
  "error": null,
  "created_at": "2026-08-18T02:15:00Z",
  "updated_at": "2026-08-18T02:17:18Z"
}
```

`file_health` 值：

```text
available
partial
not_created
missing
invalid
unreadable
deleted
```

## 6.3 Progress

```json
{
  "percent": 46,
  "estimated": true,
  "elapsed_seconds": 138,
  "estimated_total_seconds": 300,
  "estimated_remaining_seconds": 162
}
```

规则：

1. `percent` 必须单调不下降。
2. `estimated=true` 时，前端不得把百分比解释为板端真实完成比例。
3. 转写阶段默认约占 `0–20%`。
4. 全文可用后，纪要生成阶段默认从 `20%` 平滑到 `99%`。
5. 只有 `review_ready` 或 `finalized` 才能返回 `100%`。
6. 板端真实阶段变化时，Gateway 可以向前校正进度，但不能回退。

## 6.4 MeetingResultV1

Gateway 必须把 Harness 原始结果规范化为稳定的 UI 数据结构。正式前端不直接依赖 Harness 内部文件格式。

```json
{
  "schema_version": "meeting-result.v1",
  "meeting_id": "meeting-a4b8c91d210f",
  "result_revision": 1,
  "language": "zh-CN",
  "duration_ms": 2412000,
  "generated_at": "2026-08-18T02:20:13Z",
  "availability": {
    "transcript": true,
    "speakers": true,
    "minutes": true,
    "chapters": true,
    "decisions": true,
    "action_items": true,
    "evidence": true,
    "formal_version": false
  },
  "transcript": {
    "complete": true,
    "segment_count": 284,
    "segments": [
      {
        "segment_id": "seg-000001",
        "start_ms": 8000,
        "end_ms": 22000,
        "speaker_id": "spk-001",
        "text": "我们今天先确认端侧会议助手的整体链路。",
        "chapter_id": "chapter-001",
        "confidence": null,
        "review_status": "pending",
        "user_edited": false
      }
    ]
  },
  "speakers": [
    {
      "speaker_id": "spk-001",
      "display_name": "发言人 001",
      "segment_count": 98,
      "duration_ms": 866000,
      "user_renamed": false
    }
  ],
  "minutes": {
    "overview": "本次会议围绕端侧会议助手的通信链路、会议库交互和后续实现顺序展开。",
    "outline": [
      {
        "node_id": "minutes-node-001",
        "level": 1,
        "title": "当前进展",
        "text": null,
        "evidence_ids": [],
        "review_status": "reviewed",
        "user_edited": false
      },
      {
        "node_id": "minutes-node-002",
        "level": 2,
        "title": "通信链路",
        "text": "PC、Gateway 与 RK1828 之间已完成任务创建、音频传输、状态查询和结果回传。",
        "evidence_ids": ["ev-001"],
        "review_status": "reviewed",
        "user_edited": false
      }
    ]
  },
  "chapters": [
    {
      "chapter_id": "chapter-001",
      "index": 1,
      "title": "项目进展与当前边界",
      "summary": "确认通信、上传、状态回传和结果读取已经完成。",
      "start_ms": 0,
      "end_ms": 522000,
      "evidence_ids": ["ev-001"],
      "review_status": "reviewed",
      "user_edited": false
    }
  ],
  "decisions": [
    {
      "decision_id": "decision-001",
      "text": "正式首页采用会议库结构，新建会议通过弹窗选择音频来源。",
      "evidence_ids": ["ev-002"],
      "review_status": "reviewed",
      "user_edited": false
    }
  ],
  "action_items": [
    {
      "action_id": "action-001",
      "text": "将定稿设计迁移到独立前端项目。",
      "owner": null,
      "due_date": null,
      "evidence_ids": ["ev-003"],
      "review_status": "pending",
      "user_edited": false
    }
  ],
  "evidence": [
    {
      "evidence_id": "ev-001",
      "segment_id": "seg-000094",
      "start_ms": 751000,
      "end_ms": 763000,
      "speaker_id": "spk-002",
      "quote": "PC 把音频通过局域网发给开发板，结果再返回 PC。"
    }
  ],
  "diagnostics": null
}
```

重要规则：

- `owner` 和 `due_date` 未在会议中明确时必须为 `null`。
- `evidence_ids` 只能引用真实存在的证据。
- `quote` 必须能够回到真实转写片段。
- `confidence=null` 表示当前链路未提供稳定置信度，不得补造。
- `review_status` 枚举为 `pending`、`reviewed`、`edited`。
- 不可用的结果区块返回 `null`，已生成但没有项目时返回空数组 `[]`。
- `diagnostics` 默认不返回；只有 `include=diagnostics` 时返回小型技术信息。
- `quality.status=pass` 等 Harness 内部技术字段不得被 UI 解释为内容质量通过。

### 6.4.1 部分结果示例

```json
{
  "schema_version": "meeting-result.v1",
  "meeting_id": "meeting-a4b8c91d210f",
  "result_revision": 1,
  "availability": {
    "transcript": true,
    "speakers": true,
    "minutes": false,
    "chapters": false,
    "decisions": false,
    "action_items": false,
    "evidence": true,
    "formal_version": false
  },
  "transcript": {
    "complete": true,
    "segment_count": 284,
    "segments": []
  },
  "speakers": [],
  "minutes": null,
  "chapters": null,
  "decisions": null,
  "action_items": null,
  "evidence": [],
  "diagnostics": null
}
```

## 6.5 MeetingDraft

草稿保存用户可编辑内容，不修改原始 Harness 结果文件。

```json
{
  "schema_version": "meeting-draft.v1",
  "meeting_id": "meeting-a4b8c91d210f",
  "revision": 4,
  "base_result_revision": 1,
  "updated_at": "2026-08-19T03:10:00Z",
  "dirty": false,
  "content": {
    "title": "研发方案评审",
    "speaker_names": {
      "spk-001": "发言人 001",
      "spk-002": "发言人 002"
    },
    "transcript_edits": [
      {
        "segment_id": "seg-000001",
        "text": "我们今天先确认端侧会议助手的整体链路。",
        "speaker_id": "spk-001"
      }
    ],
    "minutes": {},
    "chapters": [],
    "decisions": [],
    "action_items": [],
    "review_marks": {
      "decision-001": "reviewed",
      "action-001": "pending"
    }
  }
}
```

草稿规则：

1. 原始时间点和证据关系不可由普通编辑直接删除。
2. 发言人重命名通过 `speaker_names` 保存，并同步应用到全文和证据展示。
3. 全文修改通过 `transcript_edits` 保存，不覆盖原始识别文件。
4. `PUT draft` 使用修订号防止覆盖较新的修改。
5. 会议 `finalized` 后草稿锁定，v1.0 不支持解除确认后继续编辑。

## 6.6 ExportItem

```json
{
  "format": "html",
  "state": "ready",
  "file_name": "formal_minutes.html",
  "size_bytes": 182344,
  "created_at": "2026-08-19T03:20:00Z",
  "error": null,
  "content_url": "/api/meetings/meeting-a4b8c91d210f/exports/html"
}
```

`state` 枚举：

```text
queued
generating
ready
failed
```

---

## 7. 接口总览

### 7.1 系统与连接

| 方法 | 路径 | 用途 | 实现状态 |
| --- | --- | --- | --- |
| GET | `/api/info` | Gateway 发现和版本 | 已有，需扩展 |
| GET | `/api/system/status` | 聚合 Gateway、会议库、存储和板端状态 | 新增 |
| GET | `/api/board/health` | RK1828 健康检查 | 已有 |
| POST | `/api/system/reveal` | 按白名单打开本地目录 | 新增 |

### 7.2 会议库与处理

| 方法 | 路径 | 用途 | 实现状态 |
| --- | --- | --- | --- |
| GET | `/api/meetings` | 搜索、筛选、分页 | 新增 |
| POST | `/api/meetings` | 创建持久化会议记录 | 改造 |
| GET | `/api/meetings/{meeting_id}` | 元数据、状态、进度和能力 | 改造 |
| PUT | `/api/meetings/{meeting_id}/audio` | 上传完整音频并开始处理 | 扩展多格式 |
| GET | `/api/meetings/{meeting_id}/audio` | 支持 Range 的音频播放 | 新增 |
| GET | `/api/meetings/{meeting_id}/result` | 部分或完整规范化结果 | 改造 |
| POST | `/api/meetings/{meeting_id}/cancel` | 取消录音、上传或处理 | 已有，需持久化 |
| POST | `/api/meetings/{meeting_id}/retry` | 按范围重试 | 新增 |
| GET | `/api/meetings/{meeting_id}/draft` | 读取当前草稿 | 新增 |
| PUT | `/api/meetings/{meeting_id}/draft` | 保存草稿 | 新增 |
| POST | `/api/meetings/{meeting_id}/finalize` | 确认并生成正式版本 | 新增 |
| GET | `/api/meetings/{meeting_id}/exports` | 获取导出清单 | 新增 |
| GET | `/api/meetings/{meeting_id}/exports/{format}` | 读取 HTML、TXT 或 JSON | 新增 |
| POST | `/api/meetings/{meeting_id}/audio/delete` | 单独删除原始音频 | 新增 |
| POST | `/api/meetings/{meeting_id}/rescan` | 重新扫描本地会议文件 | 新增 |
| POST | `/api/meetings/{meeting_id}/reveal` | 打开会议、音频或导出目录 | 新增 |
| DELETE | `/api/meetings/{meeting_id}?mode=index_only` | 仅从会议库索引移除无效记录 | 新增 |

### 7.3 板端录音

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/meetings/{meeting_id}/record/start` | 开始板端录音 |
| GET | `/api/meetings/{meeting_id}/record` | 查询板端录音状态 |
| POST | `/api/meetings/{meeting_id}/record/stop` | 结束录音并开始处理 |

PC 录音由浏览器 MediaRecorder 完成，结束后使用普通会议创建和音频上传接口。

### 7.4 设置与存储

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/settings` | 读取设备和本地设置 |
| PUT | `/api/settings` | 保存设置 |
| POST | `/api/settings/board/check` | 检查候选板端地址 |
| POST | `/api/settings/storage/check` | 检查候选会议库目录 |
| GET | `/api/storage` | 总容量、分类占用和可用空间 |
| GET | `/api/storage/meetings` | 按会议列出音频占用 |
| POST | `/api/storage/cleanup-temp` | 清理可安全删除的临时文件 |

---

## 8. 系统与连接接口

## 8.1 GET /api/info

用途：判断 Gateway 是否在线以及前后端版本是否兼容。

响应：

```json
{
  "service": "meeting-agent-gateway",
  "version": "1.0.0",
  "api_contract_version": "meeting-agent.api.v1",
  "status": "ready",
  "local_only": true,
  "base_url": "http://127.0.0.1:8787",
  "board_url": "http://10.10.22.36:18080",
  "capabilities": {
    "meeting_library": true,
    "local_upload": true,
    "pc_record": true,
    "board_record": true,
    "partial_result": true,
    "draft": true,
    "finalize": true,
    "audio_delete": true
  }
}
```

如果浏览器无法建立 HTTP 连接，应直接显示 `meeting_gateway_offline.html` 对应状态。Gateway 离线时不存在可返回的 API 错误 JSON。

## 8.2 GET /api/system/status

响应：

```json
{
  "gateway": {
    "status": "ready",
    "version": "1.0.0"
  },
  "meeting_library": {
    "status": "available",
    "path": "D:\\Meeting_Agent_fresh\\runtime\\meeting_library",
    "writable": true
  },
  "storage": {
    "status": "ok",
    "free_bytes": 130996502528,
    "required_bytes_for_new_meeting": 0
  },
  "board": {
    "status": "online",
    "board_id": "linaro-alip",
    "address": "10.10.22.36",
    "port": 18080,
    "busy": false,
    "active_meeting_id": null,
    "model_profile": "qwen3-4b-v104-ctx16k"
  },
  "capabilities": {
    "can_create_meeting": true,
    "can_process_audio": true,
    "can_start_board_recording": true,
    "can_view_library": true
  },
  "timestamp": "2026-08-19T03:00:00Z"
}
```

状态映射：

| 条件 | UI |
| --- | --- |
| Gateway 请求失败 | PC 本地服务未连接页 |
| Gateway 在线，Board 离线 | RK1828 未连接页；会议库仍可查看 |
| 会议库不可读 | 结果或会议库不可用状态 |
| 存储不足 | 本地空间不足页 |

## 8.3 GET /api/board/health

沿用当前代理接口。成功响应：

```json
{
  "status": "ready",
  "board_id": "linaro-alip",
  "protocol_version": "board-agent.v1",
  "agent_version": "0.2.0",
  "model_profile": "qwen3-4b-v104-ctx16k",
  "busy": false,
  "active_task_id": null,
  "local_only": true,
  "timestamp": "2026-08-19T03:00:00Z",
  "gateway": {
    "service": "meeting-agent-gateway",
    "version": "1.0.0",
    "local_only": true
  }
}
```

板端无法访问：

```http
HTTP/1.1 502 Bad Gateway
```

```json
{
  "error": {
    "code": "BOARD_UNREACHABLE",
    "message": "RK1828 未连接",
    "retryable": true,
    "retry_scope": null
  },
  "request_id": "req-..."
}
```

## 8.4 POST /api/system/reveal

只允许打开预定义目录，不接受任意绝对路径。

请求：

```json
{
  "target": "meeting_library"
}
```

`target` 枚举：

```text
meeting_library
gateway_scripts
```

响应：

```json
{
  "opened": true,
  "target": "meeting_library"
}
```

---

## 9. 会议库接口

## 9.1 GET /api/meetings

查询参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `q` | string | 空 | 会议名称搜索，不区分大小写 |
| `status` | string | `all` | `all`、`processing`、`failed`、`review`、`confirmed`、`deleted` |
| `source` | string | 空 | `local_upload`、`pc_record`、`board_record` |
| `date_from` | date | 空 | 起始日期 |
| `date_to` | date | 空 | 结束日期 |
| `sort` | string | `updated_desc` | `updated_desc`、`created_desc`、`title_asc` |
| `page` | integer | `1` | 页码 |
| `page_size` | integer | `30` | 每页数量 |

示例：

```text
GET /api/meetings?q=方案&status=review&page=1&page_size=30
```

响应：

```json
{
  "items": [],
  "page": 1,
  "page_size": 30,
  "total": 7,
  "has_more": false,
  "facets": {
    "all": 7,
    "processing": 1,
    "failed": 1,
    "review": 2,
    "confirmed": 2,
    "deleted": 1
  }
}
```

筛选映射：

| UI 筛选 | 服务端条件 |
| --- | --- |
| `processing` | `recording`、`uploading`、`processing`、`finalizing` |
| `failed` | `state=failed` |
| `review` | `state=review_ready` |
| `confirmed` | `state=finalized` 且音频未删除 |
| `deleted` | `state=finalized` 且 `audio.state=deleted` |

搜索无结果返回 `200` 和空数组，不返回 `404`。

## 9.2 POST /api/meetings

创建会议库记录，不要求前端传 `task_kind`。

请求：

```json
{
  "title": "接口契约复盘",
  "source_type": "local_upload",
  "language": "zh-CN",
  "source_file": {
    "name": "interface_review.m4a",
    "size_bytes": 181440000,
    "mime_type": "audio/mp4",
    "last_modified_at": "2026-08-19T02:40:00Z"
  }
}
```

字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `title` | 是 | 1–200 个字符 |
| `source_type` | 是 | 三种会议来源之一 |
| `language` | 否 | 默认 `zh-CN` |
| `source_file` | 本地上传时是 | 文件元数据，不包含文件内容 |

响应：

```http
HTTP/1.1 201 Created
```

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "title": "接口契约复盘",
  "state": "created",
  "phase": "awaiting_source",
  "source_type": "local_upload",
  "created_at": "2026-08-19T02:42:00Z"
}
```

冲突：当前 MVP 只有一个活动板端任务，不做排队。

```http
HTTP/1.1 409 Conflict
```

```json
{
  "error": {
    "code": "BOARD_BUSY",
    "message": "当前已有会议正在处理",
    "retryable": true,
    "details": {
      "active_meeting_id": "meeting-active-001"
    }
  },
  "request_id": "req-..."
}
```

## 9.3 GET /api/meetings/{meeting_id}

返回 `MeetingDetail`。该接口用于高频轮询，不得包含完整全文和完整纪要。

成功：`200 OK`。

不存在：`404 MEETING_NOT_FOUND`。

`seq` 每次状态变化时递增。前端必须忽略小于当前 `seq` 的乱序响应。

## 9.4 PUT /api/meetings/{meeting_id}/audio

请求体是完整音频二进制，不使用 multipart。

请求头：

```text
Content-Type: audio/mp4
Content-Length: 181440000
X-File-Name: interface_review.m4a
X-File-SHA256: 64-character-lowercase-hex
```

规则：

1. 支持 WAV、MP3、M4A、FLAC、AAC 和 OGG。
2. Gateway 先把完整原始文件保存到会议目录。
3. 非 WAV 文件在 PC 本地转换成板端处理 WAV。
4. 板端仍只接收规范化 WAV。
5. 不支持断点续传。
6. 浏览器到 Gateway 或 Gateway 到板端中断后，从头重新发送完整文件。
7. `.part` 文件不得被标记为完整音频。
8. 文件完整性由 `Content-Length` 和可选 SHA-256 验证。
9. 最大上传保护值初始沿用 `4 GiB`，不代表 120 分钟性能承诺。

接收成功并开始后续处理：

```http
HTTP/1.1 202 Accepted
```

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "state": "processing",
  "phase": "converting",
  "audio": {
    "state": "converting",
    "original_name": "interface_review.m4a",
    "size_bytes": 181440000,
    "input_verified": true
  },
  "progress": {
    "percent": 0,
    "estimated": true,
    "elapsed_seconds": 0,
    "estimated_total_seconds": 300
  }
}
```

存储不足：

```http
HTTP/1.1 507 Insufficient Storage
```

```json
{
  "error": {
    "code": "STORAGE_INSUFFICIENT",
    "message": "本地空间不足",
    "retryable": true,
    "retry_scope": "upload",
    "details": {
      "required_bytes": 3328599654,
      "free_bytes": 2576980377
    }
  },
  "request_id": "req-..."
}
```

网络中断：

```json
{
  "error": {
    "code": "UPLOAD_INTERRUPTED",
    "message": "音频传输中断",
    "phase": "uploading",
    "retryable": true,
    "retry_scope": "upload",
    "preserved": {
      "audio": true,
      "transcript": false,
      "speakers": false,
      "summary": false,
      "formal_version": false
    }
  },
  "request_id": "req-..."
}
```

此处 `preserved.audio=true` 表示 Gateway 已完整保存原始文件；板端未完成的输入必须从头重传。

## 9.5 GET /api/meetings/{meeting_id}/result

查询参数：

```text
include=transcript,speakers,minutes,chapters,decisions,action_items,evidence
```

默认返回当前已经可用的全部产品结果。处理中的调用规则：

| 状态 | 行为 |
| --- | --- |
| 全文尚未完成 | `409 RESULT_NOT_READY` |
| 全文已完成、纪要生成中 | `200`，返回全文、发言人和证据；其他区块为 `null` |
| 处理完成 | `200`，返回完整 `MeetingResultV1` |
| 结果文件缺失 | `409 RESULT_MISSING` |
| 结果文件损坏 | `500 RESULT_INVALID` |

正式前端在 `availability.transcript` 从 `false` 变为 `true` 时调用一次部分结果接口。完成后再调用一次完整结果接口。

## 9.6 POST /api/meetings/{meeting_id}/cancel

请求：

```json
{}
```

响应：

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "state": "cancelled",
  "phase": "cancelled",
  "audio": {
    "state": "available",
    "playable": true
  },
  "preserved": {
    "audio": true,
    "transcript": true,
    "speakers": true,
    "minutes": false
  },
  "capabilities": {
    "can_retry_all": true,
    "can_retry_summary": false
  }
}
```

幂等规则：

- 重复取消已取消任务返回 `200` 和当前状态。
- 已 `finalized` 的会议返回 `409 INVALID_MEETING_STATE`。
- 取消期间不得被后台 Worker 改回 `processing` 或 `completed`。

## 9.7 POST /api/meetings/{meeting_id}/retry

请求：

```json
{
  "scope": "summary"
}
```

`scope`：

| 值 | 用途 | 前置条件 |
| --- | --- | --- |
| `upload` | 从 Gateway 本地副本重新完整发送到板端 | 原始音频可用 |
| `all` | 从分段开始重新处理 | 原始音频可用 |
| `summary` | 只重新生成纪要、章节、决策和待办 | 全文和发言人可用 |
| `exports` | 只重试失败的正式格式 | 已确认草稿可用 |

响应：

```http
HTTP/1.1 202 Accepted
```

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "state": "processing",
  "phase": "synthesizing",
  "retry_scope": "summary",
  "result_revision": 1,
  "availability": {
    "transcript": true,
    "speakers": true,
    "minutes": false,
    "chapters": false,
    "decisions": false,
    "action_items": false,
    "evidence": true,
    "formal_version": false
  }
}
```

重试规则：

- `summary` 重试必须保持 `segment_id` 和 `speaker_id` 稳定。
- `all` 重试会增加 `result_revision`，可能重建片段 ID。
- 有未保存草稿时执行 `all` 重试返回 `409 DRAFT_CONFLICT`，除非请求显式包含 `discard_draft=true`。
- 已确认会议不能重跑 v1.0 正式结果。

## 9.8 GET /api/meetings/{meeting_id}/draft

尚未产生用户修改时，可以返回由当前结果初始化的 revision 0 草稿。

```json
{
  "schema_version": "meeting-draft.v1",
  "meeting_id": "meeting-a4b8c91d210f",
  "revision": 0,
  "base_result_revision": 1,
  "updated_at": null,
  "dirty": false,
  "content": {}
}
```

## 9.9 PUT /api/meetings/{meeting_id}/draft

请求：

```json
{
  "expected_revision": 4,
  "base_result_revision": 1,
  "content": {
    "title": "研发方案评审",
    "speaker_names": {
      "spk-001": "发言人 001"
    },
    "transcript_edits": [],
    "minutes": {},
    "chapters": [],
    "decisions": [],
    "action_items": [],
    "review_marks": {}
  }
}
```

响应：

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "revision": 5,
  "base_result_revision": 1,
  "saved_at": "2026-08-19T03:10:00Z",
  "review": {
    "pending_count": 3,
    "reviewed_count": 6,
    "dirty": false
  }
}
```

修订冲突：

```http
HTTP/1.1 409 Conflict
```

```json
{
  "error": {
    "code": "DRAFT_REVISION_CONFLICT",
    "message": "草稿已被较新的修改更新",
    "retryable": false,
    "details": {
      "expected_revision": 4,
      "current_revision": 5
    }
  },
  "request_id": "req-..."
}
```

前端必须保留内存中的用户修改，不能因保存失败清空编辑内容。

## 9.10 POST /api/meetings/{meeting_id}/finalize

请求：

```json
{
  "draft_revision": 5,
  "formats": ["html", "txt", "json"],
  "confirmed": true
}
```

要求：

- `confirmed` 必须为 `true`。
- 至少选择一种格式。
- `draft_revision` 必须等于当前草稿修订号。
- 会议必须为 `review_ready`。
- 使用 `Idempotency-Key` 防止重复生成。

响应：

```http
HTTP/1.1 202 Accepted
```

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "state": "finalizing",
  "phase": "exporting",
  "draft_revision": 5,
  "exports": [
    { "format": "html", "state": "queued" },
    { "format": "txt", "state": "queued" },
    { "format": "json", "state": "queued" }
  ]
}
```

生成完成后：

```text
state = finalized
availability.formal_version = true
capabilities.can_edit = false
capabilities.can_finalize = false
capabilities.can_delete_audio = true
```

某一种格式失败时，其他成功格式仍保留，前端按格式显示结果。只重试失败格式时使用：

```json
{
  "scope": "exports",
  "formats": ["txt"]
}
```

## 9.11 GET /api/meetings/{meeting_id}/exports

响应：

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "state": "finalized",
  "items": [
    {
      "format": "html",
      "state": "ready",
      "file_name": "formal_minutes.html",
      "size_bytes": 182344,
      "created_at": "2026-08-19T03:20:00Z",
      "content_url": "/api/meetings/meeting-a4b8c91d210f/exports/html",
      "error": null
    }
  ]
}
```

## 9.12 GET /api/meetings/{meeting_id}/exports/{format}

`format`：

```text
html
txt
json
```

响应头：

| 格式 | Content-Type |
| --- | --- |
| HTML | `text/html; charset=utf-8` |
| TXT | `text/plain; charset=utf-8` |
| JSON | `application/json; charset=utf-8` |

HTML 默认使用 `Content-Disposition: inline`，TXT 和 JSON 默认使用 `attachment`。

## 9.13 GET /api/meetings/{meeting_id}/audio

用于工作区和全文回放。

必须支持：

```text
Range: bytes=start-end
Accept-Ranges: bytes
206 Partial Content
```

音频已删除：

```http
HTTP/1.1 410 Gone
```

```json
{
  "error": {
    "code": "AUDIO_DELETED",
    "message": "原始音频已删除",
    "retryable": false
  },
  "request_id": "req-..."
}
```

## 9.14 POST /api/meetings/{meeting_id}/audio/delete

只允许用户已确认会议。

请求：

```json
{
  "confirmation": "删除音频"
}
```

响应：

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "audio": {
    "state": "deleted",
    "playable": false,
    "deleted_at": "2026-08-19T03:30:00Z"
  },
  "freed_bytes": 509503788,
  "retained": {
    "transcript": true,
    "speakers": true,
    "minutes": true,
    "chapters": true,
    "decisions": true,
    "action_items": true,
    "evidence_text": true,
    "evidence_timestamps": true,
    "formal_versions": true
  }
}
```

删除范围：

- Gateway 会议目录中的原始音频。
- 为处理生成的音频副本。
- 板端尚未清理的任务输入副本。

不得删除：

- `result.json`。
- `draft.json`。
- 正式 HTML、TXT、JSON。
- 证据文字和时间点。

## 9.15 POST /api/meetings/{meeting_id}/rescan

用于会议结果缺失或损坏页。

请求：

```json
{}
```

响应：

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "file_health": {
    "metadata": "available",
    "source_audio": "available",
    "result": "missing",
    "draft": "not_created",
    "formal_html": "not_created",
    "formal_txt": "not_created",
    "formal_json": "not_created"
  },
  "capabilities": {
    "can_retry_all": true,
    "can_remove_index": true
  },
  "scanned_at": "2026-08-19T03:35:00Z"
}
```

## 9.16 POST /api/meetings/{meeting_id}/reveal

请求：

```json
{
  "target": "meeting_dir"
}
```

`target`：

```text
meeting_dir
audio
exports
```

服务端根据 `meeting_id` 解析白名单路径，禁止客户端提供任意文件系统路径。

## 9.17 DELETE /api/meetings/{meeting_id}?mode=index_only

当前 UI 只要求移除无效索引，不删除本地目录。

响应：

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "removed_from_library": true,
  "files_deleted": false,
  "files_retained": true
}
```

v1.0 不提供“永久删除整场会议及全部文件”的正式入口。

---

## 10. 板端录音接口

## 10.1 POST /api/meetings/{meeting_id}/record/start

请求：

```json
{
  "device_id": "rk1828-main-mic"
}
```

响应：

```http
HTTP/1.1 202 Accepted
```

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "recording_id": "recording-12c90a10",
  "state": "recording",
  "recording": {
    "state": "recording",
    "device_id": "rk1828-main-mic",
    "started_at": "2026-08-19T04:00:00Z",
    "elapsed_seconds": 0,
    "audio_saved": true,
    "connection": "online"
  }
}
```

录音状态枚举：

```text
starting
recording
stopping
stopped
disconnected
unknown
failed
```

## 10.2 GET /api/meetings/{meeting_id}/record

响应：

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "recording_id": "recording-12c90a10",
  "state": "recording",
  "device_id": "rk1828-main-mic",
  "started_at": "2026-08-19T04:00:00Z",
  "elapsed_seconds": 1106,
  "audio_saved": true,
  "connection": "online",
  "error": null
}
```

连接中断时不得直接声明录音丢失：

```json
{
  "state": "unknown",
  "connection": "disconnected",
  "audio_saved": null,
  "error": {
    "code": "BOARD_RECORDING_STATE_UNKNOWN",
    "retryable": true
  }
}
```

重新连接后再次调用该接口确认录音是否继续。

## 10.3 POST /api/meetings/{meeting_id}/record/stop

请求：

```json
{}
```

响应：

```http
HTTP/1.1 202 Accepted
```

```json
{
  "meeting_id": "meeting-a4b8c91d210f",
  "recording_id": "recording-12c90a10",
  "recording": {
    "state": "stopped",
    "elapsed_seconds": 1106,
    "audio_saved": true
  },
  "state": "processing",
  "phase": "transcribing"
}
```

板端结束录音后直接使用板端文件处理，不需要再经过 PC 上传音频。

---

## 11. 设置接口

## 11.1 GET /api/settings

响应：

```json
{
  "device_name": "会议室 RK1828",
  "board": {
    "address": "10.10.22.36",
    "port": 18080,
    "base_url": "http://10.10.22.36:18080"
  },
  "model_profile": "qwen3-4b-v104-ctx16k",
  "meeting_library_path": "D:\\Meeting_Agent_fresh\\runtime\\meeting_library",
  "keep_audio_until_finalized": true,
  "default_export_formats": ["html", "txt", "json"],
  "default_language": "zh-CN"
}
```

## 11.2 PUT /api/settings

请求：

```json
{
  "device_name": "会议室 RK1828",
  "board": {
    "address": "10.10.22.36",
    "port": 18080
  },
  "meeting_library_path": "D:\\Meeting_Agent_fresh\\runtime\\meeting_library",
  "keep_audio_until_finalized": true,
  "default_export_formats": ["html", "txt", "json"],
  "default_language": "zh-CN"
}
```

规则：

- 地址必须是合法 IP 或主机名。
- 端口必须为 `1–65535`。
- 会议库目录必须存在或可创建，并且可写。
- 至少保留一种默认导出格式。
- `keep_audio_until_finalized=false` 在 v1.0 不允许自动删除音频；该字段只表示确认前必须保留。
- 修改板端地址后 Gateway 应原子替换后续连接配置。

## 11.3 POST /api/settings/board/check

请求：

```json
{
  "address": "10.10.22.36",
  "port": 18080
}
```

响应：

```json
{
  "status": "online",
  "board_id": "linaro-alip",
  "protocol_version": "board-agent.v1",
  "agent_version": "0.2.0",
  "model_profile": "qwen3-4b-v104-ctx16k",
  "compatible": true,
  "latency_ms": 18
}
```

检查成功不自动保存设置。

## 11.4 POST /api/settings/storage/check

请求：

```json
{
  "path": "D:\\Meeting_Agent_fresh\\runtime\\meeting_library"
}
```

响应：

```json
{
  "exists": true,
  "writable": true,
  "total_bytes": 214748364800,
  "free_bytes": 130996502528,
  "compatible": true
}
```

---

## 12. 存储接口

## 12.1 GET /api/storage

响应：

```json
{
  "path": "D:\\Meeting_Agent_fresh\\runtime\\meeting_library",
  "writable": true,
  "total_bytes": 214748364800,
  "used_bytes": 83751862272,
  "free_bytes": 131001502528,
  "status": "ok",
  "categories": {
    "audio_bytes": 58841051955,
    "results_bytes": 12025908429,
    "exports_bytes": 1825361100,
    "temp_bytes": 11059500800,
    "other_bytes": 0
  },
  "thresholds": {
    "warning_free_bytes": 10737418240,
    "minimum_free_bytes": 3221225472
  },
  "updated_at": "2026-08-19T04:10:00Z"
}
```

`status`：

```text
ok
warning
insufficient
unavailable
```

## 12.2 GET /api/storage/meetings

查询参数：

```text
sort=audio_size_desc&page=1&page_size=30
```

响应：

```json
{
  "items": [
    {
      "meeting_id": "meeting-a4b8c91d210f",
      "title": "MVP 边界与需求调研",
      "meeting_state": "finalized",
      "audio_state": "available",
      "audio_size_bytes": 463470592,
      "meeting_date": "2026-08-16T02:00:00Z",
      "can_delete_audio": true
    }
  ],
  "page": 1,
  "page_size": 30,
  "total": 1,
  "has_more": false
}
```

## 12.3 POST /api/storage/cleanup-temp

请求：

```json
{
  "categories": ["temp"]
}
```

只允许清理：

- 失败上传的 `.part`。
- 已完成任务的可重建中间文件。
- 过期 Worker 临时日志副本。

不得清理：

- 原始音频。
- 结果文件。
- 草稿。
- 正式版本。
- 当前活动任务文件。

响应：

```json
{
  "freed_bytes": 11059500800,
  "deleted_file_count": 42,
  "skipped_active_file_count": 3,
  "storage": {
    "free_bytes": 142061003328,
    "status": "ok"
  }
}
```

---

## 13. UI 页面与接口映射

| UI 文件或页面 | 主要接口 | 行为 |
| --- | --- | --- |
| `meeting_library_all.html` | `GET /api/meetings` | 搜索、筛选、分页和状态数量 |
| `meeting_library_empty.html` | `GET /api/meetings` | `total=0` 时显示空会议库 |
| 搜索无结果状态 | `GET /api/meetings?q=...` | `items=[]`，保留筛选条件 |
| 新建会议弹窗 | `GET /api/system/status`、`POST /api/meetings` | 根据能力启用三种来源 |
| `meeting_local_wav.html` | `POST /api/meetings`、`PUT /audio` | 多格式导入、完整上传、本地转换 |
| `meeting_pc_record.html` | 浏览器 MediaRecorder、`POST /api/meetings`、`PUT /audio` | 麦克风异常由浏览器处理 |
| `meeting_board_record.html` | `POST /record/start`、`GET /record`、`POST /record/stop` | 板端录音与断线确认 |
| `meeting_processing.html` | `GET /api/meetings/{id}`、`GET /result`、`POST /cancel` | 轮询状态，全文完成后提前读取 |
| `meeting_processing_interrupted.html` | `GET meeting`、`POST /retry` | `scope=upload`，从头传输 |
| `meeting_processing_failed.html` | `GET result`、`POST /retry` | 全文失败重试全部；纪要失败只重试 summary |
| `meeting_review_workspace.html` | `GET result`、`GET/PUT draft`、`POST finalize`、音频接口 | 编辑、核对、证据、确认和删除音频 |
| `meeting_full_playback.html` | `GET result`、`GET audio` | Range 播放、时间点跳转和全文搜索 |
| `meeting_formal_minutes.html` | `GET exports/html` | 显示正式 HTML 和打印 |
| `meeting_device_offline.html` | `GET /api/board/health` | Gateway 正常、板端离线 |
| `meeting_gateway_offline.html` | `GET /api/info` | 网络请求失败时由前端显示 |
| `meeting_settings.html` | `GET/PUT settings`、板端与存储检查 | 保存本地设置 |
| `meeting_storage_management.html` | `GET storage`、`GET storage/meetings`、音频删除、临时清理 | 真实空间管理 |
| `meeting_storage_insufficient.html` | `GET storage`、音频删除 | 释放足够空间后重新开始 |
| `meeting_result_unavailable.html` | `GET meeting`、`POST rescan`、`POST retry`、`DELETE index_only` | 文件缺失、损坏和正式版本降级查看 |

---

## 14. 前端轮询规则

### 14.1 会议处理

```text
创建或上传完成后：每 1 秒查询 GET /api/meetings/{id}
全文可用后：每 2 秒查询
进入终态后：停止轮询
```

规则：

1. 前端必须使用 `seq` 忽略乱序响应。
2. 状态接口不得携带完整 `MeetingResultV1`。
3. `availability.transcript` 首次变为 `true` 时读取部分结果。
4. `state=review_ready` 时读取完整结果。
5. `state=failed` 时停止轮询并按 `error.retry_scope` 显示操作。
6. `state=cancelled` 时停止轮询。
7. 后台标签页可将轮询降到 5 秒，回到前台立即刷新。

### 14.2 板端录音

```text
record/start 成功后：每 1 秒查询 GET /record
连接失败：显示状态未知，不自动判定录音结束
连接恢复：立即重新查询 GET /record
```

### 14.3 不使用 SSE

v1.0 继续使用轮询，不实现 SSE 或 WebSocket。状态接口保持小型响应，避免频繁传输全文。

---

## 15. 本地文件结构与生命周期

目标目录：

```text
D:\Meeting_Agent_fresh\runtime\meeting_library\
  meetings.db
  settings.json
  meetings\
    <meeting_id>\
      metadata.json
      source.<original_ext>
      processing.wav
      result.json
      draft.json
      file_manifest.json
      exports\
        formal_minutes.html
        formal_minutes.txt
        formal_result.json
        manifest.json
      logs\
        gateway.log
        board_task.json
```

规则：

- 如果原始输入为 WAV，可以只保留 `source.wav`，不重复生成相同的 `processing.wav`。
- 非 WAV 输入必须在 PC 本地转换，不上传公共云。
- Gateway 向板端发送规范化 WAV。
- `result.json` 保存 Gateway 规范化后的 `meeting-result.v1`，原始 Harness 结果可作为诊断产物单独保留。
- `draft.json` 只保存用户修改和核对状态。
- 正式版本不依赖原始音频继续存在。
- 删除音频后，证据时间点保留，但音频播放能力关闭。
- 删除音频操作不得删除会议目录。
- `meetings.db` 是会议列表索引，目录文件是可恢复数据来源。
- `rescan` 可以依据 `metadata.json` 和 `file_manifest.json` 重建文件健康状态。

### 15.1 生命周期矩阵

| 场景 | 原始音频 | 全文 | 纪要 | 草稿 | 正式版本 |
| --- | --- | --- | --- | --- | --- |
| 上传中断 | Gateway 完整副本存在时保留 | 无 | 无 | 无 | 无 |
| 转写失败 | 保留 | 可能无 | 无 | 无 | 无 |
| 纪要失败 | 保留 | 保留 | 无或部分 | 无 | 无 |
| 用户取消 | 保留完整文件 | 已完成部分可保留 | 已完成部分可保留 | 保留 | 保留既有版本 |
| 正式确认 | 保留 | 保留 | 保留 | 锁定 | 生成 |
| 删除音频 | 删除 | 保留 | 保留 | 保留 | 保留 |
| 移出索引 | 保留 | 保留 | 保留 | 保留 | 保留 |

---

## 16. Board Agent 内部接口

正式前端不得调用本节接口。Gateway 负责协议转换。

### 16.1 当前已实现

```text
GET  http://10.10.22.36:18080/v1/health
POST http://10.10.22.36:18080/v1/tasks
GET  http://10.10.22.36:18080/v1/tasks/{task_id}
PUT  http://10.10.22.36:18080/v1/tasks/{task_id}/audio
POST http://10.10.22.36:18080/v1/tasks/{task_id}/cancel
GET  http://10.10.22.36:18080/v1/tasks/{task_id}/result
```

当前任务快照关键字段：

```json
{
  "task_id": "task-5eda41930494",
  "meeting_id": "meeting-a4b8c91d210f",
  "task_kind": "harness_meeting_v0",
  "state": "processing",
  "stage": "llm_summary",
  "seq": 8,
  "created_at": "2026-08-18T02:15:00Z",
  "updated_at": "2026-08-18T02:17:18Z",
  "error": null,
  "input_size": 509503788,
  "input_sha256": "64-character-lowercase-hex",
  "input_verified": true,
  "harness_model_profile": "qwen3-4b-v104-ctx16k",
  "artifact_refs": {},
  "harness_elapsed_seconds": null,
  "harness_stage_details": {
    "status": "running"
  }
}
```

当前完整结果响应：

```json
{
  "task_id": "task-5eda41930494",
  "meeting_id": "meeting-a4b8c91d210f",
  "result": {},
  "artifact_refs": {}
}
```

### 16.2 正式 UI 需要补充的板端能力

| 能力 | 推荐内部接口 |
| --- | --- |
| 转写完成后提前读取部分结果 | `GET /v1/tasks/{task_id}/result?scope=transcript` |
| 只重试纪要 | `POST /v1/tasks/{task_id}/retry`，`scope=summary` |
| 板端录音开始 | `POST /v1/recordings` |
| 板端录音状态 | `GET /v1/recordings/{recording_id}` |
| 板端录音结束 | `POST /v1/recordings/{recording_id}/stop` |
| 清理板端音频副本 | `POST /v1/tasks/{task_id}/audio/delete` |

如果短期内不扩展 Board Agent，Gateway 可以通过 Harness 阶段文件和现有板端脚本完成适配，但浏览器接口不得因此改变。

---

## 17. TypeScript 参考类型

```ts
export type MeetingSourceType =
  | 'local_upload'
  | 'pc_record'
  | 'board_record';

export type MeetingState =
  | 'created'
  | 'recording'
  | 'uploading'
  | 'processing'
  | 'review_ready'
  | 'finalizing'
  | 'finalized'
  | 'failed'
  | 'cancelled';

export type MeetingPhase =
  | 'awaiting_source'
  | 'recording'
  | 'uploading'
  | 'converting'
  | 'transcribing'
  | 'synthesizing'
  | 'exporting'
  | 'ready'
  | 'cancelled';

export type AudioState =
  | 'pending'
  | 'recording'
  | 'uploading'
  | 'converting'
  | 'available'
  | 'deleted'
  | 'missing'
  | 'unreadable';

export type ReviewStatus =
  | 'pending'
  | 'reviewed'
  | 'edited';

export interface ResultAvailability {
  transcript: boolean;
  speakers: boolean;
  minutes: boolean;
  chapters: boolean;
  decisions: boolean;
  action_items: boolean;
  evidence: boolean;
  formal_version: boolean;
}

export interface MeetingCapabilities {
  can_cancel: boolean;
  can_retry_all: boolean;
  can_retry_summary: boolean;
  can_edit: boolean;
  can_save_draft: boolean;
  can_finalize: boolean;
  can_play_audio: boolean;
  can_delete_audio: boolean;
  can_reveal_files: boolean;
  can_remove_index: boolean;
}

export interface MeetingProgress {
  percent: number;
  estimated: boolean;
  elapsed_seconds: number;
  estimated_total_seconds: number | null;
  estimated_remaining_seconds: number | null;
}

export interface ApiError {
  code: string;
  message: string;
  phase?: MeetingPhase;
  retryable: boolean;
  retry_scope?: 'upload' | 'all' | 'summary' | 'exports';
  preserved?: {
    audio: boolean;
    transcript: boolean;
    speakers: boolean;
    summary: boolean;
    formal_version: boolean;
  };
  details?: Record<string, unknown>;
}

export interface TranscriptSegment {
  segment_id: string;
  start_ms: number;
  end_ms: number;
  speaker_id: string;
  text: string;
  chapter_id: string | null;
  confidence: number | null;
  review_status: ReviewStatus;
  user_edited: boolean;
}

export interface Speaker {
  speaker_id: string;
  display_name: string;
  segment_count: number;
  duration_ms: number;
  user_renamed: boolean;
}

export interface Evidence {
  evidence_id: string;
  segment_id: string;
  start_ms: number;
  end_ms: number;
  speaker_id: string;
  quote: string;
}

export interface Decision {
  decision_id: string;
  text: string;
  evidence_ids: string[];
  review_status: ReviewStatus;
  user_edited: boolean;
}

export interface ActionItem {
  action_id: string;
  text: string;
  owner: string | null;
  due_date: string | null;
  evidence_ids: string[];
  review_status: ReviewStatus;
  user_edited: boolean;
}

export interface MeetingResultV1 {
  schema_version: 'meeting-result.v1';
  meeting_id: string;
  result_revision: number;
  language: string;
  duration_ms: number;
  generated_at: string;
  availability: ResultAvailability;
  transcript: {
    complete: boolean;
    segment_count: number;
    segments: TranscriptSegment[];
  } | null;
  speakers: Speaker[] | null;
  minutes: unknown | null;
  chapters: unknown[] | null;
  decisions: Decision[] | null;
  action_items: ActionItem[] | null;
  evidence: Evidence[] | null;
  diagnostics: Record<string, unknown> | null;
}
```

正式项目应由 OpenAPI 或共享 schema 自动生成这些类型，避免手工维护两份定义。

---

## 18. 错误码清单

### 18.1 通用

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `INVALID_JSON` | JSON 无法解析 |
| 400 | `VALIDATION_FAILED` | 字段校验失败 |
| 404 | `NOT_FOUND` | 路由不存在 |
| 413 | `REQUEST_TOO_LARGE` | 请求体过大 |
| 500 | `GATEWAY_INTERNAL_ERROR` | Gateway 内部错误 |

### 18.2 会议与状态

| HTTP | code | 场景 |
| --- | --- | --- |
| 404 | `MEETING_NOT_FOUND` | 会议不存在 |
| 409 | `INVALID_MEETING_STATE` | 当前状态不允许该操作 |
| 409 | `BOARD_BUSY` | 已有活动任务 |
| 409 | `RESULT_NOT_READY` | 结果尚未可用 |
| 409 | `RESULT_MISSING` | 结果文件缺失 |
| 500 | `RESULT_INVALID` | 结果文件损坏或无法解析 |
| 409 | `DRAFT_REVISION_CONFLICT` | 草稿修订冲突 |
| 409 | `DRAFT_RESULT_CONFLICT` | 草稿基于旧结果修订 |
| 423 | `MEETING_FINALIZED_LOCKED` | 正式确认后禁止编辑 |

### 18.3 音频与上传

| HTTP | code | 场景 |
| --- | --- | --- |
| 411 | `CONTENT_LENGTH_REQUIRED` | 缺少文件长度 |
| 400 | `INVALID_CONTENT_LENGTH` | 长度非法 |
| 413 | `UPLOAD_TOO_LARGE` | 超过上传保护值 |
| 415 | `UNSUPPORTED_AUDIO_FORMAT` | 格式不支持 |
| 422 | `INPUT_SHA256_MISMATCH` | 文件哈希不一致 |
| 422 | `AUDIO_DECODE_FAILED` | 无法解码文件 |
| 500 | `AUDIO_CONVERSION_FAILED` | PC 本地转换失败 |
| 502 | `UPLOAD_INTERRUPTED` | Gateway 到板端传输中断 |
| 507 | `STORAGE_INSUFFICIENT` | 本地空间不足 |
| 410 | `AUDIO_DELETED` | 音频已删除 |
| 409 | `AUDIO_DELETE_NOT_ALLOWED` | 尚未确认纪要 |
| 500 | `AUDIO_DELETE_FAILED` | 文件占用或权限错误 |

### 18.4 板端与处理

| HTTP | code | 场景 |
| --- | --- | --- |
| 502 | `BOARD_UNREACHABLE` | RK1828 无法访问 |
| 409 | `BOARD_PROTOCOL_INCOMPATIBLE` | 协议版本不兼容 |
| 500 | `SEGMENTATION_FAILED` | 说话人分段失败 |
| 500 | `ASR_FAILED` | 转写失败 |
| 500 | `TRANSCRIPT_PREPARE_FAILED` | 全文整理失败 |
| 500 | `SUMMARY_GENERATION_FAILED` | 纪要生成失败 |
| 500 | `EXPORT_FAILED` | 正式格式生成失败 |
| 409 | `TASK_CANCELLED` | 任务已取消 |

### 18.5 录音

| HTTP | code | 场景 |
| --- | --- | --- |
| 409 | `RECORDING_ALREADY_ACTIVE` | 已有板端录音 |
| 409 | `RECORDING_NOT_ACTIVE` | 当前没有录音 |
| 502 | `BOARD_RECORDING_DISCONNECTED` | 录音控制连接中断 |
| 409 | `BOARD_RECORDING_STATE_UNKNOWN` | 需要重连后确认状态 |
| 500 | `BOARD_RECORDING_FAILED` | 板端录音失败 |

### 18.6 设置与存储

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `INVALID_BOARD_ADDRESS` | 板端地址非法 |
| 400 | `INVALID_BOARD_PORT` | 端口非法 |
| 400 | `STORAGE_PATH_INVALID` | 会议库目录非法 |
| 403 | `STORAGE_NOT_WRITABLE` | 目录不可写 |
| 500 | `TEMP_CLEANUP_FAILED` | 临时文件清理失败 |

---

## 19. 安全与本地化约束

1. Gateway 默认只监听 `127.0.0.1`，不得默认暴露到局域网。
2. 浏览器只访问 Gateway，不直接访问 `10.10.22.36:18080`。
3. Gateway 与板端只在受控局域网通信。
4. 音频、ASR、说话人、纪要、草稿和正式版本不上传公共云。
5. 文件名必须净化，不得直接拼接用户输入形成路径。
6. `meeting_id` 和 `task_id` 必须由服务端生成或严格校验。
7. 打开目录接口只接受枚举目标，不接受任意路径。
8. 音频和结果接口必须设置 `Cache-Control: no-store`。
9. 日志不得记录音频正文、完整转写或用户草稿内容。
10. 删除音频必须由用户显式触发，并校验会议已确认。
11. 本接口是本地 MVP 契约，不代表生产级安全、法律合规或真实敏感会议可用。
12. 当前验证音频应继续使用非敏感演示数据。

---

## 20. 前端实现约束

1. 正式 React 前端移除原型中的设计说明、流程讲解和技术边界说明，只保留必要操作、状态、结果和安全提示。
2. 中文文案由前端按枚举和错误码映射，API 不返回大段 UI 说明。
3. 按钮是否可用优先读取 `capabilities`。
4. 不根据进度百分比推断内容质量。
5. 不把 `quality.status=pass` 显示为会议内容质量通过。
6. `owner=null` 和 `due_date=null` 显示“未提及”，不得补造。
7. 音频删除后，时间点仍可显示，但播放按钮必须禁用。
8. 保存草稿失败时必须保留当前内存编辑内容。
9. 离开有未保存修改的工作区时，由前端显示保存、放弃和继续编辑确认。
10. 上传中断不显示“继续上传”，只显示从头重试。

---

## 21. 接口验收标准

### 21.1 会议库

- Gateway 重启后历史会议仍存在。
- 搜索和状态筛选返回正确数量。
- 搜索无结果返回空数组而非错误。
- 一个会议文件损坏不影响其他会议列表。

### 21.2 上传与处理

- 支持 WAV、MP3、M4A、FLAC、AAC 和 OGG 导入。
- 非 WAV 只在 PC 本地转换。
- 不完整上传不产生正式输入文件。
- 网络中断后从头发送完整文件。
- 状态接口不携带完整结果。
- 全文完成后，纪要生成期间可读取全文和发言人。
- 完成后可读取完整规范化结果。

### 21.3 失败与重试

- 转写失败时原始音频保留。
- 纪要失败时全文和发言人保留。
- `retry(summary)` 不改变片段和发言人 ID。
- 取消后 Worker 不能把状态改回完成。
- 错误响应明确给出是否可重试和重试范围。

### 21.4 草稿与正式版本

- 发言人重命名同步应用于全文和证据。
- 草稿使用修订号防止覆盖。
- 未提及的责任人和截止时间保持 `null`。
- 正式确认后编辑入口锁定。
- HTML、TXT 和 JSON 分别记录生成结果。
- 单一格式失败不影响其他成功格式。

### 21.5 音频与存储

- 音频接口支持 Range 播放。
- 只有确认后的会议允许删除音频。
- 删除音频后全文、纪要、决策、待办、证据文字、时间点和正式版本仍存在。
- 存储不足返回 `507 STORAGE_INSUFFICIENT`。
- 临时文件清理不删除活动任务和正式数据。
- 移出无效索引不删除会议目录。

---

## 22. v1.0 明确不做

```text
音频断点续传
SSE / WebSocket
多任务排队
多个板端并行调度
公共云上传或同步
多用户、账号和权限系统
自动删除原始音频
自动补造责任人、截止时间或身份
永久删除整场会议及全部文件
正式版本解除锁定和多版本编辑
生产级加密、审计和合规承诺
内容质量自动验收
```

---

## 23. 推荐落地顺序

```text
1. 按本文建立 OpenAPI / JSON Schema
2. 生成 TypeScript 类型和前端 fixtures
3. 建立 SQLite 会议库与本地目录服务
4. 改造现有 Gateway 状态接口
5. 实现多格式导入和 PC 本地转换
6. 实现部分结果规范化
7. 开发 React 会议库、处理页和工作区
8. 实现草稿、正式确认和导出
9. 实现音频播放、删除和存储管理
10. 实现板端录音代理
11. 按 UI 流程逐项联调
```

本文作为正式 React 前端和 Gateway v1 开发的共同接口基线。后续字段调整应更新文档版本，不应由前端或后端单方面隐式修改。
