# Meeting Harness 当前架构

本文说明当前已实现的 RK1828 离线会议 Harness。它描述运行机制和发布边界，不记录机器地址、模型传输步骤或某次实验的临时状态。生产代码和测试始终高于本文档。

当前主要版本：

```text
Harness:                 2.0.0
PROMPT_VERSION:          meeting-summary.v3
PRODUCT_SUMMARY_VERSION: product-summary.v32
```

## 1. 端到端数据流

```text
source audio
-> SoX mono / 16 kHz / 16-bit PCM WAV
-> CPU/Torch 3D-Speaker
-> RTTM padding、merge、unknown gap 处理
-> speaker/unknown segment plan
-> seg_*.wav
-> persistent Qwen3-ASR Batch runner
-> segment_transcripts.json
-> canonical segments / Timeline
-> Qwen3-4B ctx16k
-> Python validation 与允许的确定性修复
-> atomic publications 与 compatibility export
```

生产入口是 [meeting_harness/main.py](../meeting_harness/main.py)，编排逻辑位于 [meeting_harness/pipeline.py](../meeting_harness/pipeline.py)。

板端部署时，仓库包 `meeting_harness/` 通常复制为 `/userdata/meeting_agent/scripts/harness/`，板端脚本则平铺到 `/userdata/meeting_agent/scripts/`。因此仓库模块名是 `meeting_harness.main`，板端模块名通常是 `harness.main`。

## 2. 阶段边界

### 2.1 Segmentation

[board_3dspeaker_segment_prepare_absorb_unknown.py](../scripts/board/board_3dspeaker_segment_prepare_absorb_unknown.py) 负责：

1. 将源音频标准化为 mono、16 kHz、16-bit PCM WAV；
2. 调用原生 CPU/Torch 3D-Speaker diarization；
3. 对 RTTM 执行 padding 和相邻段归并；
4. 吸收左右同 speaker 且不超过阈值的短 unknown gap；
5. 为其余 gap 生成 `speaker=unknown` 的兜底段；
6. 将 known/unknown 段限制在 ASR 可接受时长并切出 WAV。

该阶段只决定匿名 speaker 和时间区间，不生成转写文本。

### 2.2 Batch ASR

[board_segment_asr_batch.py](../scripts/board/board_segment_asr_batch.py) 生成 C++ runner 使用的 `job_id<TAB>wav_path` manifest，并通过常驻 Qwen3-ASR Batch runner 一次加载模型处理全部片段。

主要结果：

- `results.jsonl`：runner 原始逐段结果；
- `segment_transcripts.json/csv`：带时间、speaker、状态和文本的统一结果；
- `batch_asr_summary.json`：完成数、失败、耗时和音频统计。

`transcript_empty` 表示推理已完成但未得到有效文本，不等于执行崩溃。空文本段仍可用于时间覆盖诊断，但不会进入最终 LLM Timeline。

### 2.3 Canonical transcript

[meeting_harness/transcript.py](../meeting_harness/transcript.py) 将 ASR 结果规范化为稳定记录：

```json
{
  "segment_id": "seg-000038",
  "start_ms": 888000,
  "end_ms": 912000,
  "speaker_id": "speaker_3",
  "text": "这一段的 ASR 转写文本"
}
```

权威字段：

- `segment_id`：摘要 refs 和所有溯源信息的机器键；
- `start_ms/end_ms`：内部精确时间；
- `speaker_id`：diarization 产生的匿名 speaker；
- `text`：ASR 文本。

`timeline.txt` 是可读投影。精确评测和发布逻辑应优先读取 `03_llm_summary/canonical_segments.json`，不能依赖秒级显示文本恢复毫秒边界。

## 3. LLM 紧凑输入

为减少弱模型处理长 ID 的负担，请求内使用紧凑引用：

```text
[r38][14m48s-15m12s][sp3] 内容
```

其中：

- `r38` 对应 `seg-000038`；
- `sp3` 对应 canonical speaker；
- 显示时间用于 grounding，不替代 canonical 毫秒时间；
- 请求校验后，Harness 将所有 `r*` 和 `sp*` 展开为 canonical ID。

compact ref 和 speaker map 必须在同一请求策略内保持一致。speaker batch validator 使用全局 map，避免 batch-local 编号与 Prompt 编号不一致。

## 4. 上下文预算

当前默认值来自 [meeting_harness/main.py](../meeting_harness/main.py)：

```text
ctx:                          16384
predict:                       4096
max_tokens:                    4096
input safety reserve:           512
input token budget:           11776
chars_per_token estimate:       1.3
fixed estimate overhead:         128
```

输入预算为：

```text
ctx - max_tokens - input_safety_tokens
= 16384 - 4096 - 512
= 11776
```

固定开销和字符比例用于 [meeting_harness/chunking.py](../meeting_harness/chunking.py) 的启发式 Prompt 估算。当前不是严格 tokenizer 计数。

当前默认 `predict/max_tokens` 统一为 `4096`，为 Qwen3 thinking 和最终 JSON 预留更充足的输出空间；相应地，单个滑动窗口的启发式输入预算缩小为 `11776` tokens，长会议可能产生更多窗口请求。

当前主线不再根据预算选择一次性全量请求，统一使用 `sliding_chapter_windows`，即使输入较短也按同一协议处理。一次性全量路径仅作为历史实现保留，不属于当前运行路径。

## 5. 历史的一次性全量路径

早期实现曾在 Timeline 能放入预算时一次生成 title、overview、chapters、speakers 和 action_items。该路径保留在历史记录中，用于解释架构演进和取舍，当前生产 Harness 不再调用。

## 6. 滑动章节窗口

Harness 始终按完整 canonical segment 构造自然章节窗口，而不是对字符流硬切。

每个窗口负责：

1. 输出已完成的核心章节；
2. 为章节生成标题、摘要和关键 refs；
3. 提取已完成章节中的 action candidates；
4. 判断窗口末尾是否存在未结束话题；
5. 返回 `carryover_start_ref`。

未结束话题从 carryover 起点进入下一窗口。若模型未返回 carryover 但窗口有未覆盖尾部，Harness 可从第一条未覆盖 segment 推断 carryover。每轮必须向后推进，禁止相同起点无限循环。

滑动路径请求构成：

```text
N 个 chapter windows
+ 1 个 full-summary
+ 0 或 1 个 action-review
+ 若干 speaker batches
```

只有存在 action candidates 时才执行 action-review。

## 7. 章节范围归并

LLM 负责语义核心范围：

```text
core_start_ref
core_end_ref
```

Harness 负责最终连续范围：

- 第一章从窗口第一条 segment 开始；
- 当前章结束于下一核心章节起点之前；
- 最后一章结束于 carryover 前一条或窗口末尾；
- 低信息过渡内容可归入相邻完整范围，但不必进入章节摘要 refs；
- 最终时间从 canonical segments 回填。

允许的确定性结构修复包括：

- 普通重叠：截断前一个章节；
- 相同起点：合并无法划分的章节；
- 反向范围：归一化为有效顺序。

修复写入 `validation.json` 和 `plan.json`，不增加 LLM 重试。该机制只修复结构冲突，不判断章节语义是否正确。

## 8. Full-summary 与 refs

滑动章节完成后，full-summary 请求只接收已校验章节的 ID、标题和摘要。LLM 只生成会议标题和 overview 文本。

最终 overview refs 由 Harness 按章节顺序合并并去重，LLM 不重新选择 refs。这样保留完整溯源，同时避免模型在 thinking 中耗费输出预算讨论引用集合。

## 9. Action review

章节窗口只提取明确要求执行、确认执行或明确分配的 action candidates。普通讨论、建议和愿望不能自动升级为待办。

如果候选非空，action-review 接收候选和对应原文证据，负责复核、合并和去重。owner、deadline 和 refs 必须有原文依据；没有依据时使用 `null` 或丢弃候选。

## 10. Speaker batches

滑动路径按 `speaker_id` 聚类 canonical segments，构造独立 speaker 文档并打包请求。

规则：

- 每个输入 speaker 文档必须有一条返回结果；
- refs 必须属于对应 speaker；
- 不生成 `speaker_key_points`；
- compact speaker map 在 Prompt 和 validator 中保持一致。

单个 speaker 文档超预算时，Harness 保留按时间顺序的最长前缀，最后一个 segment 必要时按字符截断。截断信息写入：

```text
03_llm_summary/speaker_documents.json
03_llm_summary/speaker_batches.json
03_llm_summary/plan.json
```

当前没有 speaker chunk/merge，因此被截断 speaker 的总结可能遗漏后半段内容。

## 11. 请求、thinking 与缓存

[meeting_harness/llm.py](../meeting_harness/llm.py) 管理一次 `rkllm3-server` 生命周期，所有实时总结请求共享该服务。

每个请求目录通常保存：

```text
messages.json
request.json
response.json
raw_content.txt
thinking.txt
final_json.txt
status.json
validated_result.json
validation.json
```

可复用请求身份绑定：

- Prompt 和消息内容；
- 请求类型；
- ctx、predict、max_tokens、temperature；
- 模型路径、大小和 SHA-256；
- final JSON、validated result、validation 和 status 哈希。

只有 fingerprint 与产物哈希均匹配的已校验请求可以在 `--resume` 中复用。

## 12. 验证与发布

[meeting_harness/validation.py](../meeting_harness/validation.py) 和 [meeting_harness/product_summary.py](../meeting_harness/product_summary.py) 检查：

- JSON 和字段类型；
- refs 存在且属于本次输入；
- speaker refs 属于对应 speaker；
- 章节范围和顺序；
- carryover 推进；
- owner/deadline 证据；
- finish reason、thinking 闭合和输入截断；
- 最终结果能否生成完整发布结构。

产品协议的主要业务字段是 overview、chapters、speakers、action_items；内部 schema 仍保留部分空的 legacy compatibility 字段。

发布由 [meeting_harness/pipeline.py](../meeting_harness/pipeline.py) 和 [meeting_harness/artifacts.py](../meeting_harness/artifacts.py) 完成。`meeting_summary.json`、frontend、display 和 compatibility export 必须来自同一批通过验证的结果。

`meeting_result.json` 是整次运行状态的权威外壳。HTTP 成功、usage 正常或 `context_truncated=false` 只证明单次模型请求完成，不能替代最终 publication 状态。

当前主线验证状态：固定滑动窗口已在 30 个样本上完成板端验证，其中包含前 10 组和后 20 组复用既有 ASR 结果的运行。当前默认 `predict/max_tokens` 为 4096，后续质量评测统一以 4K 配置为准；一次性全量路径不再启用。

## 13. Resume

`--resume` 可在身份一致时复用：

- segmentation；
- Batch ASR；
- 已通过验证的 LLM 请求。

输入音频、阶段配置或产物身份变化时，对应阶段及其下游重新执行。重新发布前，旧的顶层 publication 和 compatibility export 会被轮转保存，避免混淆不同运行结果。

## 14. 主要产物

```text
<out-dir>/
├── run_config.json
├── stage_status.json
├── timeline.txt
├── meeting_summary.json
├── meeting_frontend.json
├── meeting_display.txt
├── meeting_result.json
├── logs/
├── 01_segments/
├── 02_batch_asr/
├── 03_llm_summary/
├── 04_compat_export/
└── runtime/
```

产物职责详见根目录 [README](../README.md)。完整转写来自 canonical ASR segments，不由 LLM 重新生成。

## 15. 已知边界

- token 预算是启发式估算；
- speaker 超预算采用前缀截断；
- 章节确定性修复只保证结构，不判断语义质量；
- 匿名 speaker 不代表真实身份；
- ASR 语义错误会成为下游事实输入；
- `chunk-overlap-segments` 当前虽属于 CLI/config，但生产 product-summary 路径不应依赖它实现固定 overlap 行为；
- 模型、数据集和上游运行时不随仓库发布。

历史部署、性能和失败实验见：

- [RK1828 / RKNN3 部署历史](rk1828_qwen_asr_llm_deployment_summary.md)
- [问题、实验与解决方案历史](rk1828_meeting_agent_issues_and_solutions.md)
- [Legacy 综合记录](history/mainDoc.md)
