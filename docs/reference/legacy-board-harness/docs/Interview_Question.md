# 端侧本地 Agent 智能会议投影系统 — 面试问题

## 一、项目概述

**端侧本地 Agent 智能会议投影系统**是一个面向 RK1828/RKNN3/RKLLM 平台的离线会议理解系统。它将一段会议录音转换为结构化的会议结果，包括会议概览、章节总结、说话人信息、行动项以及可追溯的证据引用，并将结果以 `meeting_summary`、`frontend`、`display` 和兼容格式原子发布。

项目的核心目标不是单纯做语音转文字，而是构建一条可以在端侧独立运行、可恢复、可验证、可审计的会议内容处理链路：

```text
会议音频
    │
    ▼
SoX 音频标准化
    │ mono / 16 kHz / 16 bit WAV
    ▼
CPU 说话人分离（3D-Speaker + RTTM）
    │ padding / merge / unknown 处理
    ▼
分段音频计划
    │
    ▼
Qwen3-ASR-0.6B 常驻 Batch 推理
    │
    ▼
Canonical Timeline
    │ seg-XXXXXX / 毫秒时间戳 / speaker / text
    ▼
Qwen3-4B + rkllm3-server
    │ 固定滑动章节窗口与后续聚合
    ▼
结构化会议总结 JSON
    │
    ▼
确定性校验与修复
    │ schema / 引用 / speaker / 章节连续性 / 截断
    ▼
原子发布多种产物
```

### 核心特性

| 特性 | 说明 |
|------|------|
| **完全端侧处理** | 音频、ASR、会议总结和校验主要在 RK1828 开发板及本地服务完成，不依赖云端推理 |
| **多阶段语音流水线** | 音频标准化、说话人分离、分段、ASR、时间轴规范化相互解耦 |
| **Canonical Timeline** | 用稳定的 `seg-XXXXXX` 段 ID 和毫秒时间戳作为全链路唯一事实来源 |
| **说话人分离与未知说话人兜底** | 结合 RTTM padding、相邻片段合并、短 unknown 吸收和最终 unknown 兜底，尽量覆盖全部语音 |
| **常驻 Batch ASR** | 避免逐段重复加载模型，通过批量推理显著降低整场会议的 ASR 时间 |
| **本地 Agent 总结** | Qwen3-4B 通过 `rkllm3-server` 的 OpenAI 兼容 HTTP 接口生成结构化会议结论 |
| **长会议上下文管理** | 统一采用章节滑动窗口、carryover、全文摘要和可选 action review，避免一次性全量输入 |
| **结构化输出协议** | 通过版本化 prompt 和 JSON schema 约束 overview、chapters、speakers、action_items 等字段 |
| **证据可追溯** | 结论、行动项和说话人内容关联原始 canonical segment 引用，而不是只输出无来源摘要 |
| **确定性验证** | 对 schema、引用合法性、章节连续性、speaker 归属、行动项字段和截断状态做非 LLM 校验 |
| **可恢复执行** | 根据 prompt/config/model 文件和输入 artifact SHA 计算指纹，支持复用已完成阶段并避免重复推理 |
| **原子发布** | 校验通过后一次性发布结果，防止下游读取到半成品 |
| **离线评测体系** | 覆盖 ASR、语音覆盖率、说话人、运行时间、端到端总结、引用 faithfulness 和核心内容覆盖率 |

> 当前仓库的实际代码重点是离线 Harness 和板端处理链路，不包含已经实现的 PC Web 前端、局域网服务、用户确认界面或完整产品化审计系统。这些内容主要出现在 MVP PRD 的规划中。

---

## 二、项目目录结构

```text
Meeting_Agent/
├── README.md                                  # 项目总览、当前实现边界和运行说明
├── PRD_端侧本地Agent智能会议投影系统_MVP_v1.0.md   # MVP 产品需求与规划目标
├── meeting_harness/                           # 当前有效的端到端 Harness
│   ├── main.py                                # 本地/板端入口，编排整条流水线
│   ├── pipeline.py                            # 阶段执行、resume、artifact 指纹与运行控制
│   ├── llm.py                                 # rkllm3-server HTTP 调用、响应解析和 thinking 处理
│   ├── transcript.py                          # transcript/timeline 的规范化与转换
│   ├── chunking.py                            # 长上下文章节划分和窗口构造
│   ├── summary.py                             # 会议总结请求、窗口聚合和结果合并
│   ├── product_summary.py                     # 产品级总结输出
│   ├── validation.py                          # 确定性输出校验、引用和结构修复
│   ├── artifacts.py                           # 运行产物、manifest、原子发布
│   ├── compat_export.py                       # 兼容格式导出
│   ├── display.py                             # display 产物生成
│   ├── prefix_test.py                         # prompt 前缀/上下文相关验证
│   └── __init__.py
├── scripts/
│   ├── board/                                 # 板端上传、ASR、LLM 和 Harness 脚本
│   ├── diarization/                           # 说话人分离、时间段处理和评估脚本
│   ├── local_only/                            # 本地实验、转换、探针、profile 和历史 patch
│   ├── README.md                              # 脚本索引与使用说明
│   └── generate_vcsum_technical_dataset.js    # VCSUM 技术数据处理
├── evals/
│   ├── README.md                              # 评测说明
│   ├── prompts/                               # judge prompt
│   ├── llm_judge.py                           # 当前 LLM judge 实现
│   ├── llm_judge_source.txt                   # judge 源码备份/参考实现
│   └── tools/                                 # 评测数据准备和辅助工具
├── prompts/
│   ├── README.md                              # prompt 协议说明
│   └── meeting_summary_v32_zh.md              # 与当前主线同步的可读 Prompt 协议
├── data/
│   ├── vcsum/                                 # VCSUM timeline 和 manifest
│   ├── lifelog_quant/                         # 量化相关数据
│   └── lifelog_sft/                           # SFT/训练相关数据
├── VCSum-main/                                # VCSUM 数据和参考工程
├── docs/
│   ├── architecture.md                        # 架构说明
│   ├── history/mainDoc.md                     # 历史主文档
│   ├── rk1828_meeting_agent_issues_and_solutions.md
│   ├── rk1828_qwen_asr_llm_deployment_summary.md
│   ├── resume_metrics_overview.md             # 可写入简历的指标概览
│   └── Rockchip_RK182X_*.pdf                  # RKNN3/RKNPU3 SDK 文档
├── daily/                                     # 阶段性日报和实验记录
├── output/                                    # 本地评测和运行产物
└── tests/                                     # 单元测试、Harness 测试和数据处理测试
```

### 正式实现、实验脚本和历史代码的边界

| 类别 | 典型位置 | 面试时应如何描述 |
|------|----------|------------------|
| 正式处理链路 | `meeting_harness/`、`scripts/board/` | 当前项目的主要可运行实现 |
| 评测与统计 | `evals/`、`scripts/diarization/`、`tests/` | 用于量化质量、回归和定位问题 |
| 模型转换/探针 | `scripts/local_only/conversion/`、`probes/` | 部署实验和性能验证，不是主产品流程 |
| 历史兼容/patch | `scripts/local_only/legacy/`、`board_patches/` | 保留问题排查经验，不应当当作正式架构 |
| 数据与参考工程 | `data/`、`VCSum-main/` | 评测、训练或复现实验输入 |
| 产品规划 | `PRD_*.md` | 目标形态，不能等同于当前已落地代码 |

---

## 三、总体架构与阶段编排

项目不是一个单一模型调用，而是由多个阶段组成的可恢复流水线。每个阶段产出明确的 artifact，下一个阶段只依赖规范化的中间结果。

### 3.1 分层架构

```text
┌──────────────────────────────────────────────────────────────┐
│                  Product / Output Contract                  │
│   meeting_summary / frontend / display / compat             │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                 Deterministic Validation                     │
│ schema / refs / speaker / chapter continuity / truncation    │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                  LLM Summary Layer                           │
│ sliding chapter windows + aggregation                        │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                  Canonical Timeline                          │
│ stable segment ID / time_ms / speaker / text / provenance    │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                   ASR Layer                                  │
│ Qwen3-ASR-0.6B resident batch runner                         │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│              Diarization and Audio Preparation               │
│ SoX → 3D-Speaker CPU → RTTM normalize → segment plan         │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 端到端主流程

```text
input audio
    │
    ▼
[1] audio normalize
    │ SoX 转 mono / 16kHz / 16-bit
    ▼
[2] diarization
    │ 3D-Speaker CPU 推理
    ▼
[3] RTTM post-processing
    │ padding、相邻同 speaker 合并、短 unknown 吸收、unknown 兜底
    ▼
[4] segment plan
    │ 生成需要送入 ASR 的时间区间
    ▼
[5] batch ASR
    │ Qwen3-ASR-0.6B 常驻进程
    ▼
[6] canonical timeline
    │ 规范化 seg-XXXXXX、start/end 毫秒、speaker、text
    ▼
[7] summary planning
    │ 固定滑动章节窗口与 carryover
    ▼
[8] local LLM
    │ Qwen3-4B / rkllm3-server / JSON protocol
    ▼
[9] validation
    │ 非 LLM 规则检查和结构修复
    ▼
[10] atomic export
```

### 3.3 为什么要使用中间 artifact

如果 ASR、说话人分离和 LLM 总结直接通过内存对象串接，任何阶段失败都需要从头运行，也难以定位问题。当前设计把每个阶段的输入输出保存为可检查的 artifact，并在 manifest 中记录：

- 输入文件和中间文件的 SHA 指纹；
- prompt、配置和模型文件的版本指纹；
- 阶段状态和运行时间；
- 产物路径及协议版本；
- 是否可以在 resume 时复用。

因此可以分别复现“ASR 结果不对”“章节窗口超预算”“LLM JSON 不合法”以及“发布阶段失败”等问题。

---

## 四、音频预处理与说话人分离

### 4.1 为什么先统一音频格式

板端的说话人模型和 ASR 模型对采样率、声道数、位深存在预期。入口先用 SoX 将输入统一到：

- mono；
- 16 kHz；
- 16-bit PCM WAV。

这样可以把输入格式差异限制在链路最前端，避免后续模型分别处理 MP3、双声道、44.1 kHz 或不同位深导致的隐性差异。

```text
任意会议音频
    │
    ▼
SoX normalize
    │
    └── canonical_audio.wav
```

### 4.2 说话人分离流程

当前链路使用 CPU/Torch 运行 3D-Speaker，并以 RTTM 形式表达说话人区间：

```text
canonical_audio.wav
    │
    ▼
3D-Speaker diarization
    │
    ▼
RTTM: speaker / start / duration
    │
    ▼
padding
    │ 补偿模型边界误差，减少语音被截断
    ▼
merge adjacent same-speaker segments
    │
    ▼
absorb short unknown segments
    │
    ▼
unknown fallback for uncovered speech
    │
    ▼
segment plan
```

### 4.3 unknown 说话人的处理策略

实际会议中，聚类结果可能存在短暂的 `unknown` 区间。直接丢弃会造成语音覆盖率下降，所以当前逻辑分层处理：

1. 对很短且夹在相邻已知 speaker 之间的 unknown，尝试吸收到合理的相邻片段；
2. 对仍然无法归属的语音保留 unknown，而不是静默丢弃；
3. 对 RTTM 没有覆盖但检测到语音的区间，用兜底规则生成 unknown segment；
4. 之后 ASR 仍处理这些区间，保证完整语音尽可能进入 Canonical Timeline。

这体现了一个重要设计原则：**说话人标签不确定时可以退化为 unknown，但语音内容不应该因为标签不确定而丢失。**

### 4.4 说话人分离的评测

评测同时关注“已知 speaker 是否分对”和“全部语音是否覆盖”：

| 指标 | 含义 |
|------|------|
| speech precision / recall / F1 | 语音区域检测和覆盖情况 |
| known speaker accuracy | 已识别 speaker 的标签质量 |
| known speaker recall | 已知 speaker 语音被正确归属的比例 |
| unknown-inclusive recall | 把 unknown 也作为可接受兜底后的全语音覆盖 |
| DER | 说话人分离的综合错误率，可结合 Hungarian mapping 处理匿名 speaker 标签置换 |

历史基准中，已知 speaker accuracy 约 0.9976，known recall 约 0.9437；加入 unknown 兜底后全 speech recall 可达到 1.0。具体数字取决于数据集、RTTM 和评测口径，面试时应说明这是历史实验结果而非所有输入上的保证。

### 4.5 面试追问

**Q：为什么不直接使用端侧 ASR 自己做说话人识别？**

A：ASR 的主要职责是语音识别，而说话人分离需要对声纹/说话人轨迹进行独立建模。先做 diarization，再把 speaker 区间送给 ASR，可以让 ASR 专注识别，也可以在 ASR 失败时独立调试 speaker 和文本问题。两者解耦后，分段计划还可以复用到不同 ASR 模型或不同评测中。

**Q：为什么 unknown 不能直接删除？**

A：删除 unknown 会把“无法确定说话人”错误地变成“没有这段内容”，从而影响总结、行动项和事实引用。unknown 是标签不确定性，不能等价为内容无效，所以系统保留内容并显式标注未知 speaker。

**Q：padding 和 merge 的代价是什么？**

A：padding 可以减少边界截断，但可能引入相邻说话人的少量重叠；merge 可以减少碎片和 ASR 请求数，但如果合并阈值过大，会把不应合并的内容拼在一起。因此需要通过时间轴评测和 ASR 结果共同调参，而不是只看段数。

---

## 五、Qwen3-ASR 端侧推理与 Batch 优化

### 5.1 为什么使用常驻 Batch Runner

最初逐段调用 ASR 时，每个片段可能重复进行进程通信、模型初始化或请求调度，会议段数一多，固定开销会占主导。当前做法是启动一个常驻的 Qwen3-ASR-0.6B runner，把多个 segment 组织成 batch 请求：

```text
segment plan
    │
    ├── segment 1 ─┐
    ├── segment 2 ─┤
    ├── segment 3 ─┤──► resident Qwen3-ASR-0.6B runner
    └── segment N ─┘
                         │
                         ▼
                 text + segment index
```

Batch runner 需要注意：

- 保持输入 segment 与输出结果的稳定对应关系；
- 空结果不能导致后续索引错位；
- 失败 segment 应该显式记录，而不是静默移除；
- 进程启动、ready、请求和结束状态都要写入运行记录；
- 需要限制 batch 大小，避免音频过长导致内存峰值过高。

### 5.2 历史性能结果

一次约 36 分 50 秒会议音频的历史板端结果：

| 项目 | 结果 |
|------|------:|
| 原始 ASR 段数 | 194 |
| unknown 处理后段数 | 130 |
| 逐段 ASR 耗时 | 约 858.735 s |
| Batch ASR 耗时 | 约 71.109–72.594 s |
| 加速比 | 约 12.08× |
| Batch 成功结果 | 130 段中大部分成功，历史记录有 12 段空结果 |

这些结果说明优化重点不是盲目换更大的模型，而是先消除重复启动和逐段调度开销。

### 5.3 ASR 仍然存在的问题

当前端侧 ASR 可能出现：

- 否定词识别错误；
- 数字、专有名词和术语错误；
- 责任对象或主语反转；
- unknown 碎片造成上下文断裂；
- 空结果或短片段文本质量不稳定。

因此下游总结不能把 ASR 文本当作绝对真值，而需要依靠原始 segment 引用、结构化校验和质量评测发现问题。

### 5.4 面试追问

**Q：Batch 为什么会比逐段快这么多？**

A：主要收益来自常驻模型进程和减少请求级固定开销，而不只是 GPU/CPU 并行。逐段模式会重复触发进程调度、模型访问和通信；Batch 将多个输入集中送入同一 runner，能够复用模型状态，并降低每个 segment 的平均调度成本。

**Q：Batch 输出如何避免错位？**

A：输入端为每个任务携带稳定的 segment index 或 ID，输出端按 index 写回，而不是依赖返回顺序。对空结果、异常结果和部分失败保留显式状态，最后按原始 canonical segment 顺序重建 Timeline。

**Q：为什么没有直接把所有音频一次性输入 ASR？**

A：整场音频会带来上下文长度、内存峰值和错误传播问题。按 diarization segment 处理可以保留 speaker 边界、控制请求大小，并方便重试和定位。Batch 优化解决的是多个短任务的固定开销，不等于把整场会议拼成单个超长请求。

---

## 六、Canonical Timeline：全链路事实来源

### 6.1 Timeline 的作用

Canonical Timeline 是本项目最重要的中间协议。它把说话人分离结果、ASR 文本、时间戳和来源关系统一到稳定的数据结构中，后续 LLM 总结和评测都基于它，而不是直接读取某个模型的临时输出。

典型结构如下：

```json
{
  "segments": [
    {
      "id": "seg-000123",
      "start_ms": 123000,
      "end_ms": 128500,
      "speaker": "speaker_01",
      "text": "我们需要在周五之前完成版本验证。",
      "source": "asr_batch"
    }
  ]
}
```

### 6.2 Canonical ID 为什么重要

使用稳定的 `seg-XXXXXX` ID 有几个好处：

- LLM 输出可以引用原始证据；
- 校验器可以检查引用是否存在；
- 窗口切分后仍能回指同一原始 segment；
- resume 或重复运行时可以比较输入 artifact；
- 前端、display、兼容导出都使用同一套事实来源；
- 评测可以精确定位某条结论对应的时间片段。

Prompt 中允许模型使用紧凑的 `r`/`sp` 引用以节省 token，Harness 再将它们展开成 canonical segment 引用。这样兼顾了 LLM 上下文长度和结果可追溯性。

### 6.3 为什么不直接让 LLM 读取原始 RTTM 和 ASR 文件

原始 RTTM、逐段 JSON 和临时文本的字段命名、时间单位和排序可能不一致。如果 LLM 同时接触多种格式，会增加认知负担和引用错误。Canonical Timeline 先完成：

- 时间单位统一为毫秒；
- segment 排序；
- speaker 名称规范化；
- 文本清理；
- 空结果处理；
- 来源和 segment ID 固化。

LLM 只处理一种稳定输入协议，校验器也只需要围绕一种协议实现。

---

## 七、端侧 LLM 总结架构

### 7.1 模型和服务接口

总结阶段使用本地 Qwen3-4B，并通过 RKLLM 运行时的 `rkllm3-server` 对外提供 OpenAI 兼容 HTTP 接口。这样应用层不需要直接绑定底层 C/C++ 推理细节，只需要处理：

```text
Harness
   │ HTTP request
   ▼
rkllm3-server
   │ RKLLM runtime / NPU
   ▼
Qwen3-4B
   │
   ▼
OpenAI-compatible response
```

服务启动和推理参数受到 RKNN3/RKNPU3 SDK 能力约束，重要参数包括：

- context length；
- `predict` 或最大生成 token 数；
- temperature 等生成参数；
- server ready 状态；
- HTTP 请求超时和错误处理。

### 7.2 thinking 与 final JSON 分离

Qwen3 可能返回 thinking/reasoning 内容和最终答案。应用层不能把整个响应字符串直接当作 JSON，而应：

1. 解析服务响应；
2. 分离 `<think>` 或 `reasoning_content`；
3. 提取 final content；
4. 检查 `finish_reason` 是否为 `stop`；
5. 解析 final JSON；
6. 将 thinking 和 final 的诊断信息写入运行记录，但只把协议允许的 final 内容发布给下游。

如果出现未闭合 thinking、JSON 被截断或 `finish_reason` 异常，不能仅凭 HTTP 200 判断成功。

### 7.3 当前输出协议

当前核心会议总结协议主要包含：

```text
overview
chapters
speakers
action_items
```

每类结果都应尽量包含证据引用。历史协议中还出现过 decisions 等字段，但不能把 legacy 辅助字段和当前正式四字段协议混为一谈。

示意结构：

```json
{
  "overview": {
    "text": "会议主要讨论了版本验证和交付安排。",
    "refs": ["seg-000123", "seg-000130"]
  },
  "chapters": [
    {
      "title": "版本验证计划",
      "start_ms": 120000,
      "end_ms": 420000,
      "summary": "团队确定在周五前完成验证。",
      "refs": ["seg-000123"]
    }
  ],
  "speakers": [],
  "action_items": [
    {
      "task": "完成版本验证",
      "owner": "speaker_01",
      "deadline": "周五",
      "refs": ["seg-000123"]
    }
  ]
}
```

字段具体名称以当前 prompt/schema 版本为准，面试回答时应强调**版本化协议和 schema 优先于口头约定**。

---

## 八、长上下文管理与滑动章节窗口

### 8.1 为什么主线不再单次输入完整 Timeline

端侧 Qwen3-4B 虽然配置了约 16K context，但输入不仅包括 Timeline 文本，还包括系统 prompt、结构化要求、引用约束、模型输出空间和 safety margin。如果只按字符数粗略判断，很容易出现：

- prompt 被截断；
- final JSON 没有生成完；
- `<think>` 消耗掉太多输出预算；
- 章节或行动项被放在上下文末端而丢失；
- HTTP 成功但整体结果不完整。

当前默认规划使用 `ctx=16384`、`predict/max_tokens=4096`，并保留 512-token 安全余量，因此总结输入预算约为 11776 tokens。token 估算采用启发式 `chars/token≈1.3` 和固定开销，不是严格 tokenizer，因此仍需要运行时和结果级校验。

### 8.2 当前统一路径

```text
Canonical Timeline
        │
        ▼
按 token 预算构造安全窗口
        │
        ▼
sliding chapter windows + carryover
        │
        ├── chapter summaries
        ├── full summary
        ├── optional action review
        └── speaker batches
                │
                ▼
      final structured result
```

当前 Harness 不再尝试把完整 Timeline 一次交给模型，而是统一根据 canonical segment 构造多个安全窗口：

- 每个窗口包含一段连续的 Timeline；
- 保留必要的 carryover，帮助模型理解上下文；
- 每个窗口先生成局部章节结果；
- 再生成 full summary；
- 必要时对 action_items 和 speakers 做独立批次审查；
- 最后确定性合并为正式协议。

### 8.3 “模型决定章节，Harness 修复连续范围”

模型擅长从内容中识别主题和章节标题，但不适合完全依赖它生成精确、连续且无重叠的时间范围。因此当前采用混合策略：

- LLM 负责章节语义、标题和摘要；
- Harness 根据 canonical Timeline 和排序结果确定或修复连续范围；
- 校验器检查章节是否覆盖、是否重叠、是否出现倒序或空范围。

这是一种典型的职责分离：**语义任务交给 LLM，机械约束交给确定性程序。**

### 8.4 长上下文方案的局限

当前仍有几个已知问题：

- 启发式 token 估算不等于真实 tokenizer；
- speaker 文档超预算时主要保留最长前缀，还没有完整的 chunk/merge 方案；
- 即使当前已将 `max_tokens` 提高到 `4096`，thinking 消耗过多时仍可能出现未闭合 thinking 或最终 JSON 空间不足；
- 分窗口会削弱跨窗口的全局关系；
- 章节结构修复能保证形式连续，但不能保证语义一定最优。

---

## 九、确定性校验与原子发布

### 9.1 为什么不能只依赖 LLM 自检

LLM 可能生成看起来合理但无法执行的结果，例如：

- 引用了不存在的 segment；
- speaker 名称不在 Timeline 中；
- action item 没有 owner 或证据；
- 章节时间范围重叠或倒序；
- JSON 被截断；
- 输出字段缺失或类型错误；
- 结论和引用内容不匹配。

因此项目把可靠性拆为两层：

```text
LLM：负责理解、归纳、判断语义
Harness：负责协议、索引、范围、状态和发布门禁
```

### 9.2 主要校验项

| 校验类别 | 检查内容 |
|----------|----------|
| Schema | JSON 是否可解析，字段是否存在，类型是否正确 |
| Protocol version | prompt、输出和产物版本是否匹配 |
| Reference integrity | refs 是否指向实际存在的 canonical segment |
| Speaker validity | speaker 是否来自已知 speaker 集合或合法 unknown |
| Chapter continuity | 章节是否按时间排序，是否连续、重叠或存在空洞 |
| Evidence requirement | overview/action/chapter 是否具备必要证据 |
| Action completeness | task、owner、deadline、refs 等字段是否满足当前协议 |
| Truncation | finish_reason、thinking 闭合、JSON 完整性和上下文状态 |
| Legacy compatibility | 旧字段导出是否与当前 canonical 结果一致 |

### 9.3 为什么 `context_truncated=false` 仍不代表成功

`context_truncated=false` 只能说明服务端没有报告上下文截断，不能证明：

- final JSON 完整；
- 所有章节都生成；
- 所有行动项都带引用；
- 引用都存在；
- 章节覆盖完整；
- 校验通过；
- 所有产物都成功发布。

所以真正的成功条件应该是：**服务响应正常 + final JSON 可解析 + 结构校验通过 + 引用和时间范围有效 + 所有必要产物原子发布完成。**

### 9.4 原子发布

发布阶段不应直接覆盖生产目录中的部分文件。更安全的流程是：

```text
临时运行目录
    │ 生成全部 summary/frontend/display/compat
    ▼
完整校验
    │
    ├── 失败：保留诊断产物，不更新正式结果
    │
    └── 成功
          │
          ▼
    原子 rename / commit 发布
```

这样下游不会读取到 overview 已更新、action_items 仍是旧版本的混合状态。

---

## 十、Resume、幂等性和故障恢复

### 10.1 Resume 的基本思路

长会议在板端运行时间较长，ASR 或 LLM 阶段失败后从头重跑成本很高。`pipeline.py` 通过输入和配置的指纹决定某阶段产物是否可以复用：

```text
stage input SHA
+ prompt version / SHA
+ config SHA
+ model file SHA
+ protocol version
        │
        ▼
artifact fingerprint
        │
   ┌────┴────┐
   │         │
匹配         不匹配
   │         │
复用产物     重新运行阶段
```

### 10.2 为什么要把 prompt 和模型也放入指纹

如果只比较音频 SHA，修改 prompt 或模型后仍复用旧总结，会产生隐蔽的数据不一致。结果真正依赖：

- 输入音频和 Timeline；
- 模型权重；
- prompt 文本；
- 配置参数；
- 输出协议版本。

因此这些因素都应该进入 fingerprint，才能确保“相同输入”真正意味着相同处理条件。

### 10.3 幂等性要求

重复运行同一个输入时应尽量满足：

- segment ID 稳定；
- 排序稳定；
- 产物路径稳定；
- 同一阶段可以安全复用；
- 发布过程不会留下半套结果；
- 兼容导出不会反复追加内容。

LLM 本身可能存在随机性，因此如果需要严格复现实验，还需要固定采样参数、模型版本和运行配置，并记录完整 prompt 与 response metadata。

---

## 十一、板端部署与 RKNN/RKLLM

### 11.1 板端部署架构

```text
Windows / WSL 转换与开发环境
    │ 模型转换、量化、数据准备、脚本同步
    ▼
RK1828 开发板
    │
    ├── CPU/Torch 3D-Speaker diarization
    ├── Qwen3-ASR-0.6B batch runner
    ├── rkllm3-server
    └── meeting_harness
```

RKNN3 SDK 文档涉及：

- RKNN Toolkit 和 Python 环境；
- ONNX 到 RKNN 的转换；
- Runtime、transfer proxy 和 C API；
- Qwen 系列模型的部署；
- RKLLM 模型文件、tokenizer 和 embedding 文件；
- `rkllm3-server` 的启动参数和 OpenAI 兼容接口；
- context length 与最大生成长度的关系。

### 11.2 为什么 ASR 和 LLM 的部署方式不同

ASR 需要处理大量相互独立的短音频片段，适合使用常驻 batch runner；总结模型需要处理结构化长文本，并且涉及较大的 KV cache 和 context，适合通过本地 server 提供统一接口。两者虽然都在端侧运行，但请求形态、内存压力和失败恢复方式不同。

### 11.3 历史板端资源结果

一次约 36 分 50 秒会议的历史结果：

| 项目 | 结果 |
|------|------:|
| diarization（CPU） | 约 249.443 s |
| ASR Batch | 约 72.594 s |
| server ready | 约 21.043 s |
| 单次 LLM request | 约 46.949 s |
| 整板峰值内存 | 约 2680.770 MB |
| LLM 阶段内存 | 约 1273.535 MB |
| server HWM | 约 281.625 MB |
| LLM prompt tokens | 10821 |
| LLM completion tokens | 1561 |
| total tokens | 12382 |
| context truncated | false |

这些数字用于容量规划和面试说明，不能替代在目标固件、目标模型和目标音频上的重新测量。

### 11.4 面试追问

**Q：为什么要区分模型转换机和开发板？**

A：模型转换、量化和数据生成往往需要更完整的 Python/工具链与更高算力，而开发板负责最终运行和资源验证。分开后可以提高迭代效率，但必须记录转换参数、模型 SHA 和 SDK 版本，避免“转换机可用、板端不可复现”。

**Q：context length 和最大输出长度是什么关系？**

A：context length 是输入和生成共享的总上下文容量，最大输出长度不能单独无限增加。输入越长，留给输出的空间越少；如果没有 safety margin，模型可能在 JSON 尚未闭合时达到上限。因此 Harness 需要同时规划输入预算、输出预算和安全余量。

**Q：为什么不能只看 server 的 ready 和 HTTP 200？**

A：ready 只表示服务启动，HTTP 200 只表示请求层成功。模型输出仍可能被截断、JSON 解析失败、引用不合法或通过不了最终校验。产品级成功必须由 Harness 的完整门禁决定。

---

## 十二、评测体系

项目的评测分为语音和总结两大层，并且总结层继续区分机械指标与 LLM judge 指标。

### 12.1 语音和时间轴评测

```text
参考时间轴 / TextGrid / RTTM
          │
          ▼
时间单位统一到毫秒
          │
          ▼
100 ms frame-based evaluation
          │
          ├── speech precision / recall / F1
          ├── CER / edit distance
          ├── speaker mapping accuracy
          ├── unknown coverage
          ├── DER
          └── runtime / memory
```

实现中使用 bit-parallel Levenshtein 等方法降低编辑距离计算成本，speaker 标签比较前通过 Hungarian mapping 处理匿名聚类标签不一致问题。

### 12.2 VCSUM 数据评测

VCSUM 数据用于验证会议 Timeline、窗口总结和结果稳定性。当前资料中包含 50 组数据：

- 3 组 sharing；
- 47 组 technical；
- timeline 文本和 manifest；
- 部分时间戳由固定的 24 秒/segment 生成，不能当作真实录音时间。

历史记录中有 5×5 稳定性测试 25/25、220/220 请求通过、0 重试、0 截断和 SHA 一致等结果。面试时应说明这些是特定测试集和配置下的稳定性结果。

### 12.3 端到端总结评测

| 指标 | 测量内容 |
|------|----------|
| schema pass | 输出是否满足协议结构 |
| reference validity | 引用是否存在并能回指 Timeline |
| chapter continuity | 章节时间范围是否连续、合法 |
| speaker validity | speaker 是否有来源和合法归属 |
| action completeness | 行动项字段及证据是否齐全 |
| faithfulness | 结论是否被引用内容支持 |
| core content coverage | 关键事实是否覆盖 |
| runtime | 各阶段耗时和整体耗时 |
| memory | 峰值和阶段性内存 |

### 12.4 Faithfulness 和 Core Content Coverage

LLM judge 会把 claim 分解为若干事实，按 supported、partial、missing 评估：

```text
claim_score = (supported + 0.5 × partial) / total_claims
```

核心内容覆盖率会对不同重要性赋权：

- major claim 权重 2；
- critical claim 权重 3；
- covered 得 1；
- partial 得 0.5；
- missing 得 0。

历史资料中 Faithfulness 约 91%，core content coverage 约 80%，其中后者明确标注为待专项验证的指标，不应在面试中包装成最终产品保证。

### 12.5 评测设计的关键取舍

**为什么同时需要 deterministic grader 和 LLM judge？**

- deterministic grader 适合检查 schema、ID、引用、时间范围和字段完整性，稳定、便宜、可回归；
- LLM judge 适合判断“这句话是否被上下文支持”“总结是否覆盖核心事实”等语义问题，但有模型偏差和成本；
- 二者结合，可以避免让 LLM judge 负责本应由程序精确判断的索引和格式问题。

---

## 十三、当前实现与 PRD 规划的差异

> **当前实现口径：** 总结阶段统一使用 `sliding_chapter_windows`，本地 Qwen 默认使用 4096-token 输出预算，不再启用一次性全量总结；ASR、Canonical Timeline 和 RTTM/segment 后处理沿用现有链路不变。固定滑动窗口主线已在 30 个样本上完成板端验证，后续质量评测统一以 4K 配置为准。

这是面试中非常容易被追问、也最需要诚实说明的一部分。

| 方向 | MVP PRD 目标 | 当前仓库实现 |
|------|-------------|-------------|
| 运行形态 | PC 局域网 Web + 开发板 Agent | 主要是板端/本地离线 Harness |
| 前端 | Web 投影和管理界面 | 当前仓库没有完整 PC Web 前端 |
| 输出格式 | HTML / TXT / JSON | 已有 summary/frontend/display/compat 等文件产物 |
| 本地处理 | 音频、ASR、LLM 在端侧 | 已落地主要链路 |
| 安全 | 加密、删除、审计 | PRD 规划，仓库未形成完整产品实现 |
| 用户确认 | 决策/行动项确认流程 | 当前主要做结构化输出和校验 |
| 章节总结 | 全文分章节二次汇总 | 当前统一采用滑动章节窗口、carryover 和全文二次汇总，不使用一次性全量总结 |
| 决策字段 | 独立 decisions 对象 | 当前核心协议主要是 overview/chapters/speakers/action_items，部分字段属于 legacy |
| 性能目标 | PRD 中的目标值 | 已有部分板端历史实测，仍需在目标版本上验证 |

回答项目时，应该说“当前实现了离线端侧会议 Harness，产品化 Web 和安全闭环是下一阶段”，而不是把 PRD 中的规划描述成已经上线的功能。

---

## 十四、已知问题与改进方向

### 14.1 Token 预算需要从启发式升级为真实 tokenizer

当前使用字符/token 比例和固定余量进行预算估算，适合快速控制，但不同语言、数字、代码和 JSON 字符的真实 token 密度差异很大。改进方向：

- 使用目标 Qwen tokenizer 做预计算；
- 分别统计 system prompt、Timeline、carryover 和输出预算；
- 按窗口动态留出 JSON 最小生成空间；
- 运行时继续保留 finish_reason 和 JSON 完整性门禁。

### 14.2 Speaker 长文本的窗口策略不完整

speaker 批次超预算时当前主要保留最长前缀，可能遗漏后半段发言。可以改为：

- 按 speaker 的时间顺序分块；
- 每块独立提取事实；
- 再按 speaker 聚合；
- 保留每个事实对应的原始 refs；
- 对同一 speaker 的冲突信息做确定性去重或 LLM 复核。

### 14.3 ASR 质量问题会向总结层传播

否定、数字、术语和责任对象错误可能让 LLM 生成流畅但事实不对的摘要。改进方向：

- 对关键数字、否定和专有名词做二次识别；
- 引入低置信度片段标记；
- 对 action owner/deadline 进行专门复核；
- 用原始音频或局部重识别支持人工/系统抽查。

### 14.4 章节结构和语义仍需解耦

当前 Harness 可以修复章节的连续时间范围，但范围连续不代表章节语义一定合理。可以增加：

- 章节边界候选打分；
- 内容相似度和主题变化检测；
- 跨窗口章节去重；
- 章节摘要和原文覆盖率检查。

### 14.5 LLM 输出协议需要继续收紧

full_summary 可能因为 thinking 消耗过多而未闭合，行动项也可能把“建议”升级成“已经决定的任务”。可以：

- 限制 thinking 或将规划与最终 JSON 分开请求；
- 为 action item 增加“原文明确指派”的判断条件；
- 强制每条 action item 提供 owner/deadline 的证据或明确 unknown；
- 对决策、建议、行动项使用不同 schema。

### 14.6 产品化能力尚未完成

PRD 中的 PC Web、局域网通信、加密存储、删除策略、审计日志和正式确认流程还需要独立实现。当前 Harness 已经提供了较好的离线处理和验证基础，但不能直接等同于最终产品。

### 14.7 历史凭据副本风险

仓库中历史的 `evals/llm_judge.py.txt` 文本副本曾包含疑似明文 API key，而当前 `evals/llm_judge.py` 已改为环境变量读取。正确的处理方式是：

1. 立即吊销/轮换疑似泄露的 key；
2. 从所有历史/备份文本中移除凭据；
3. 使用环境变量或 secret manager；
4. 增加 secret scanning；
5. 不要因为文件扩展名是 `.txt` 就认为它不属于仓库安全边界。

---

## 十五、面试问题与参考答案

### Q1：请用一分钟介绍这个项目。

**参考回答：**

这是一个运行在 RK1828 端侧的离线会议理解系统。输入会议音频后，系统先用 SoX 统一音频格式，再用 CPU 3D-Speaker 做说话人分离和时间段处理，之后通过常驻的 Qwen3-ASR-0.6B Batch Runner 生成带 speaker 和毫秒时间戳的 Canonical Timeline。总结阶段使用本地 Qwen3-4B，通过 rkllm3-server 生成带证据引用的结构化会议摘要；当前主线不再尝试一次性输入完整 Timeline，而是统一使用滑动章节窗口、carryover、全文摘要、待办复核和 speaker batches。最后用确定性校验器检查 schema、引用、speaker、章节连续性、行动项和截断状态，并原子发布多种结果文件。项目重点解决的是端侧资源约束、长上下文、结果可追溯和失败可恢复，而不是只把几个模型串起来。

### Q2：这个项目最核心的工程设计是什么？

**参考回答：**

核心是把模型能力和确定性工程约束分开。LLM 负责语义理解、总结和行动项提取；Harness 负责 Canonical Timeline、segment ID、时间范围、引用合法性、schema、token 预算、resume 和原子发布。这样可以利用 LLM 的灵活性，又不会把 ID、索引、连续性和发布一致性完全交给概率模型。

### Q3：为什么要引入 Canonical Timeline？

**参考回答：**

它是整个系统的唯一事实来源，把 diarization、ASR 和时间戳规范化成稳定协议。后续总结、引用、窗口切分、评测和导出都引用同一组 segment ID，避免不同阶段各自维护一套时间轴导致错位。它还让 resume、审计和错误定位变得可行。

### Q4：为什么采用“先 diarization，再 ASR”的顺序？

**参考回答：**

因为说话人区间和文字识别是不同问题。先得到 speaker/time segment，可以让 ASR 在有边界的音频上工作，同时把 speaker 信息稳定地附加到文本。这样 ASR、speaker 和总结可以独立替换和评测；如果 ASR 失败，也不会丢失原始说话人时间结构。

### Q5：unknown speaker 的兜底逻辑解决了什么问题？

**参考回答：**

它把 speaker 识别的不确定性和语音内容是否存在分开。短 unknown 可能吸收到相邻已知 speaker，但无法安全归属的部分保留为 unknown；RTTM 没覆盖但有语音的区间也用 unknown 兜底。这样不会为了追求 speaker 标签完整而牺牲 speech recall。

### Q6：Batch ASR 的主要性能收益来自哪里？

**参考回答：**

主要来自常驻 runner 和减少逐段固定开销。逐段模式会重复进行进程调度、通信和模型访问，Batch 把多个 segment 交给同一常驻进程处理，并通过稳定 ID 写回结果。历史 36 分钟会议上，逐段 ASR 约 858 秒，Batch 约 71–73 秒，约 12 倍加速。

### Q7：为什么不把整场会议直接输入 ASR？

**参考回答：**

整场输入会带来上下文、内存和错误恢复问题，也会丢失明确的 speaker 边界。按 segment 处理可以控制请求大小、支持部分失败和重试，并把 speaker 标签与每段文本稳定关联。Batch 解决的是调度开销，不等同于不分段。

### Q8：为什么统一采用滑动章节窗口？

**参考回答：**

虽然 context length、system prompt、Timeline 文本和输出预算仍需要估算，但当前主线不再尝试把完整 Timeline 一次输入模型，而是统一按 canonical segment 构造安全窗口。每个窗口提取已完成章节并通过 carryover 推进未结束话题，全部窗口完成后再生成全文摘要，必要时复核待办，并通过 speaker batches 生成发言人总结。这样可以降低长输入导致的截断、JSON 不完整和一次请求失败风险；最终仍由确定性校验器检查结果是否完整。

### Q9：为什么不完全依赖 LLM 生成章节时间范围？

**参考回答：**

LLM 擅长判断主题，不擅长稳定地产生连续、无重叠、无空洞的机械范围。系统让 LLM 生成章节语义，让 Harness 根据 Canonical Timeline 修复和校验 start/end，确保形式合法。语义决策和确定性约束分工可以减少长会议中的结构错误。

### Q10：HTTP 200 或 context_truncated=false 能否说明总结成功？

**参考回答：**

不能。它们只说明服务层或上下文层没有报告失败，不能说明 JSON 完整、引用合法、章节完整或 action item 有证据。系统必须继续执行 final JSON 解析、finish_reason、thinking 闭合、schema、refs、speaker、章节和发布校验，全部通过后才能认为阶段成功。

### Q11：为什么需要 thinking 和 final JSON 分离？

**参考回答：**

thinking 是模型内部推理/诊断信息，不属于下游稳定协议；final JSON 才是业务结果。如果直接把整个 response 当 JSON，会遇到 `<think>`、reasoning_content、markdown fence 或截断问题。分离后既可以记录推理诊断，又能让下游只消费版本化结构化结果。

### Q12：如何保证行动项不是模型臆造的？

**参考回答：**

要求 action item 绑定 canonical refs，并检查任务、owner、deadline 等字段。更严格的规则是：只有原文明确表达了任务、责任人或截止时间时才填入对应字段，否则使用 unknown 或不输出。LLM judge 可以判断语义支持，但引用存在性和字段格式由 deterministic validator 检查。

### Q13：如何设计 resume？

**参考回答：**

每个阶段都保存 artifact 和 manifest，并把输入 SHA、prompt/config/model SHA、协议版本写入 fingerprint。resume 时只有指纹完全匹配才复用；输入、模型、prompt 或配置变化就重新运行对应阶段。这样既避免重复处理长音频，也避免错误地复用旧模型或旧协议的结果。

### Q14：如何处理幂等性和原子性？

**参考回答：**

中间产物使用稳定 ID、稳定排序和稳定路径；重复运行不会追加重复内容。最终输出先写临时目录，完成所有校验后通过原子操作替换正式目录，避免下游读取到混合版本。对于失败运行保留诊断产物，但不更新正式发布结果。

### Q15：为什么同时需要 deterministic grader 和 LLM judge？

**参考回答：**

schema、ID、引用存在性、时间范围和字段完整性是机械约束，应该用 deterministic grader，成本低且回归稳定。faithfulness、核心事实覆盖和语义支持关系适合 LLM judge，但它有评委偏差和成本。两者分工能让评测既可靠又覆盖语义质量。

### Q16：Hit/Recall 类指标和 faithfulness 有什么区别？

**参考回答：**

语音或检索 recall 关注需要的信息是否被找回来；faithfulness 关注最终输出的 claim 是否被检索上下文支持。即使 Timeline 覆盖了信息，LLM 仍可能总结错或添加无依据内容；反过来，某条引用不是参考答案的原始位置，也可能包含足够信息支撑正确回答。因此需要同时测召回和生成忠实度。

### Q17：当前项目有哪些性能瓶颈？

**参考回答：**

历史链路中 CPU diarization 是明显耗时阶段，逐段 ASR 的重复开销也曾很高，Batch 后已显著改善。LLM 阶段受 context、生成长度、KV cache 和服务调度影响。优化顺序应先用 profile 拆解启动、音频预处理、diarization、ASR、LLM 和发布耗时，再决定是优化算法、批处理、模型量化还是减少 token。

### Q18：为什么项目要记录内存峰值？

**参考回答：**

端侧设备的内存比云端更受限，模型权重、KV cache、ASR batch、Timeline 和 Python 对象可能同时存在。只看平均内存会漏掉窗口聚合或服务启动时的峰值。记录整板峰值、阶段峰值和 server HWM，才能判断是降低 batch、缩短窗口、释放中间对象还是调整模型参数。

### Q19：项目的最大技术风险是什么？

**参考回答：**

不是某个单独模型的准确率，而是多个不确定阶段叠加后的端到端可靠性：diarization 可能错 speaker，ASR 可能错数字和否定，LLM 可能截断或臆造，长上下文可能漏掉后半段。当前通过 Canonical Timeline、引用、窗口管理、deterministic validation、resume 和评测把风险显式化，但仍需要持续提升真实会议上的 ASR 和核心内容覆盖率。

### Q20：你觉得这个项目最难的部分是什么？你是怎么处理的？

**参考回答：**

我觉得最难的是端侧 NPU 对上下文长度的限制。我们使用的本地模型上下文上限大约是 16K，长会议的完整内容不可能一次性放进去；但如果只是把内容简单切成几段、每段独立总结，再循环地把结果继续交给模型，前面的细节会不断丢失，循环本身也不能真正解决上下文不够的问题。

我的处理方式是先根据 token 预算把内容分成多个章节窗口，但窗口边界不是简单按固定长度切，而是让模型判断哪些章节已经完整结束、窗口末尾的话题是否还没有结束。如果话题没有结束，模型会返回它应该从哪一段继续，下一窗口就从这个位置接着处理；如果章节已经完成，就不重复处理。最后再把各个窗口的章节结果和关键信息合并起来。这样不是简单地“超长了就截断”，也不是无限循环调用，而是在有限的 16K 上下文里尽量保留章节之间的关系和关键信息。这是我认为项目里最需要权衡、也最难落地的部分。

### Q21：如果继续迭代，你会优先做什么？

**参考回答：**

第一优先级是把 token 预算从启发式升级为目标模型真实 tokenizer，并完善 speaker 长文本分块，降低长会议漏信息和 JSON 截断概率。第二优先级是加强 ASR 的数字、否定、术语和责任对象纠错，并让 action item 具备更严格的证据门禁。第三优先级是把当前离线 Harness 封装为 PRD 需要的局域网服务和前端，同时补齐加密、删除和审计闭环。所有改动都应继续通过 Canonical Timeline 和 deterministic evaluator 做回归。

### Q22：当前实现和 PRD 的差距如何解释？

**参考回答：**

当前仓库完成度最高的是端侧离线处理和 Harness 验证链路；PRD 还规划了 PC Web、局域网通信、加密、删除、审计、用户确认等产品能力。面试时我会明确区分“代码已经实现”“有实验验证”“文档规划中”三种状态，不会把 PRD 目标冒充成当前功能。现有 Harness 是后续产品化的底层基础。

### Q23：发现仓库中有历史明文 API key，你会怎么处理？

**参考回答：**

先按真实泄露处理，立即吊销和轮换 key；再清理历史备份和文本副本，改用环境变量或 secret manager；增加 secret scanning 和提交前检查；检查 git 历史和 CI 日志是否已经暴露。`.txt`、`.backup` 或测试文件同样属于仓库安全边界，不能因为不是正式 Python 文件就忽略。

### Q24：这个项目处理一场会议大概需要多长时间？各个模块分别耗时多少？

**参考回答：**

我们的测试会议一般在 35 到 50 分钟左右。在数据集测试中，模型和环境已经准备好的情况下，一场会议从音频处理到本地 LLM 总结，整体大约需要 4 到 6 分钟。

分模块来看，音频预处理和说话人分离大约需要 2 到 3 分钟；Qwen3-ASR 的常驻 Batch 推理通常在 1 分钟左右；本地 LLM 的总结处理大约需要 1 到 2 分钟。这个时间不是只由会议时长决定的，还和有效语音量、说话人分段数量以及最终转写文本的长度有关。比如一场较短但发言密集的会议，处理时间可能接近上限；一场较长但有效内容较少的会议，处理时间不一定更长。

以上是当前数据集测试中的大致范围，前提是模型已经部署完成，不包括模型转换、模型传输和环境准备。正式链路使用常驻 Batch Runner，能够避免逐段启动 ASR 带来的额外开销。

### Q25：模型采用什么量化方式？

**参考回答：**

模型采用 W4A16 量化，也就是模型权重使用 4 bit 表示，激活值和主要计算保持 16 bit。这样可以显著降低模型权重的存储占用和访存带宽，同时尽量保持计算精度。

**追问：你的 KV Cache 量化是怎么配置的？**

**参考回答：**

KV Cache 采用 INT4 存储、FP16 计算的配置。推理过程中，K 和 V 以 INT4 格式保存，并结合对应的 scale 在读取时进行反量化，之后以 FP16 参与 Attention 计算。这样可以降低 KV Cache 随上下文增长带来的内存占用。

### Q26：为什么采用 W4A16？

**参考回答：**

我们在 FP16、W8A16、W4A16 以及同时量化权重和激活的方案之间进行了权衡。FP16 的精度最好，但模型权重占用和访存压力较大，不适合端侧资源限制；W8A16 的精度更稳，但压缩比例不如 W4A16。相比 W4A8 或 W8A8，W4A16 只量化权重，保留 FP16 激活和计算，可以减少激活量化带来的额外精度损失，同时硬件实现也更容易稳定。综合模型大小、内存带宽、推理速度和精度后，选择了 W4A16。

**追问：为什么 KV Cache 采用 INT4 存储、FP16 计算？**

**参考回答：**

KV Cache 的候选方案主要有 FP16、INT8→FP16 和 INT4→FP16。FP16 KV Cache 精度最好，但它会随着上下文长度增长，占用较多运行时内存；INT8→FP16 的精度损失更小，但节省的内存不如 INT4。我们选择 INT4→FP16，是因为当前场景对运行时内存和长上下文能力更敏感，所以接受 INT4 带来的精度损失。

---

## 十六、面试中应主动说明的事实边界

1. **当前项目主体是离线端侧 Harness，不是已经完成的 Web 产品。**
2. **Qwen3-ASR-0.6B 和 Qwen3-4B 是当前链路中的本地模型，部署依赖 RKNN/RKLLM SDK 和板端运行时。**
3. **Canonical Timeline 是全链路事实来源，LLM 输出必须通过 refs 回指它。**
4. **模型负责语义，Harness 负责协议、索引、时间范围、恢复和发布门禁。**
5. **当前主线统一使用滑动章节窗口；一次性全量请求只属于历史实现，不再作为生产路径。**
6. **历史性能和质量指标只对特定设备、模型、数据和配置有效。**
7. **PRD 中的前端、局域网、安全和确认闭环不能描述成当前已经实现。**
8. **评测中约 80% 的 core content coverage 是待专项验证的暂定口径，不能直接等同于最终准确率。**
9. **数据、模型、运行产物和一次性实验脚本不属于正式产品代码；面试时应以当前有效代码和文档口径为准。**
10. **Judge 凭据只能通过环境变量或 secret manager 提供，不能写入源码、文本副本、日志或 Git；历史副本中的凭据应立即清理并轮换。**

---

## 十七、可背诵的项目总结

> 我做的是一个运行在 RK1828 端侧的离线智能会议理解系统。系统先通过 SoX 统一音频格式，再用 3D-Speaker 做说话人分离和 RTTM 后处理，生成带 speaker 和毫秒时间戳的分段计划。随后我用常驻的 Qwen3-ASR-0.6B Batch Runner 进行语音识别，并将结果规范化为 Canonical Timeline，保证后续所有总结、引用和评测都基于稳定的 segment ID。会议总结使用本地 Qwen3-4B 和 rkllm3-server；当前主线统一按 canonical Timeline 使用滑动章节窗口、carryover 和聚合流程，再生成全文摘要、待办复核和发言人总结。LLM 只负责语义理解，schema、引用、speaker、章节连续性、截断检测、resume 和原子发布由 Harness 确定性处理。项目的主要工程难点是端侧资源限制、批量推理、长上下文、结果可追溯和失败恢复；当前已经有板端性能和 30 个样本的端到端验证，但 Web 前端、局域网通信、加密和审计等 PRD 产品能力仍属于后续落地范围。
