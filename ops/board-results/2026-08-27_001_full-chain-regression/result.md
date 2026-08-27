# 2026-08-27 全链路回归结果

- **任务 ID**：`2026-08-27_001`
- **执行方式**：前端 `5174` → Gateway `8788` → Board Agent `18082` → Harness
- **输入**：非敏感演示 WAV，与前一轮前端验证使用同一音频
- **状态**：`blocked`
- **一句话结论**：音频上传、说话人处理和转写已完成，但 `llm_summary` 阶段因缺少 4 个发言人摘要触发校验失败，纪要及正式版本未生成。

## 运行标识

| 字段 | 值 |
| --- | --- |
| Meeting ID | `meeting-1d9ca8d1c0b9` |
| Board Task ID | `task-2a83a3a8a98a` |
| Run ID | `mtg_9c6133819814365e` |
| 失败阶段 | `llm_summary` |
| 返回码 | `7` |
| 阶段耗时 | `451.799` 秒 |
| 失败代码 | `validation_failed` |

## 失败原因

```text
LLM 摘要校验失败：missing speaker summaries:
speaker_0, speaker_1, speaker_2, speaker_5
```

## 阶段结果

| 阶段 | 结果 |
| --- | --- |
| 音频上传 | succeeded |
| 说话人处理 | succeeded |
| Batch ASR / 转写 | succeeded |
| LLM 纪要生成 | failed |
| 章节生成 | 未完成 |
| 正式版本导出 | 未完成 |

转写产物仍然保留：

```text
segment_count=174
nonempty_segment_count=166
empty_segment_count=8
speaker_count=7（含 unknown）
```

## 结果可用性

```text
transcript=true
speakers=true
minutes=false
chapters=false
decisions=false
action_items=false
evidence=false
formal_version=false
```

音频和转写未删除，摘要和正式版本未生成。

## Gateway 观察

Gateway 日志显示：

```text
POST /api/meetings/meeting-35917c22985f/finalize -> 404
```

当前 Gateway 能力中 `finalize=false`，因此最终纪要保存问题还存在接口能力缺失，不是单纯的前端显示问题。

## 安全回传说明

本目录只放置经过筛选的失败诊断和日志摘录，不包含：

```text
音频
完整 worker.log
完整转写文本
完整 prompt 或模型响应
blocks/
requests/
绝对路径
```

`run_report.md` 和 `run_report.json` 本轮未生成，因为完整 Harness 目录尚未在开发机完成回传；不得用局部诊断数据代替聚合报告。
