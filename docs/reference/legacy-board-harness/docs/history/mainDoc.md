# RK1828 本地模型会议转录（Legacy）

> **历史综合记录。** 本文保留早期方案、部署命令、模型实验和阶段结论，路径与“当前”表述可能已被后续代码替代。现行入口见 [项目 README](../../README.md)，现行机制见 [架构说明](../architecture.md)。
>
> 文中的版本、目录和性能数据只代表对应实验阶段，不应直接作为当前生产操作手册。

## 概述

本项目旨在将本地会议录音转换为带时间戳和 speaker 的转录文本，再由本地 LLM 生成带证据引用的会议纪要。目标部署环境为配备 RK1828 计算加速卡的小型设备。本文同时包含 RKNN3 v1.0.0/v1.0.4、SenseVoice、Qwen2.5、Qwen3、ctx8k/ctx16k 和多个 runner 阶段的历史演进记录。

> **当前主线：** 运行时固定使用 `sliding_chapter_windows`，本地 Qwen 默认使用 `ctx=16384`、`predict/max_tokens=4096` 和 512-token 输入安全余量，对应启发式输入预算为 11776 tokens；不再使用一次性全量总结。ASR、canonical Timeline 和 RTTM/segment 后处理沿用现有链路不变；固定滑动窗口主线已在 30 个样本上完成板端验证，其中包括前 10 组和后 20 组复用既有 ASR 结果的运行。当前操作应以根目录 README 和 `docs/architecture.md` 为准。

## 2026-08-12 历史方案快照

### 三端路径与同步规范

```text
Windows 开发机：D:\project\Meeting_Agent
独立 WSL：      /root/Developer/Meeting_Agent
RK1828 板端：   /userdata/meeting_agent
板端登录：      linaro@<board-host>
```

- Windows 到 WSL：在 WSL 上主动通过 `scp` 从 Windows 拉取文件；
- WSL 到 RK1828：统一使用 `rsync --bwlimit=10m`，默认限速约 10 MB/s；
- WSL 转换脚本平铺到 `/root/Developer/Meeting_Agent/scripts/`；
- 板端脚本平铺到 `/userdata/meeting_agent/scripts/`；
- 仓库源码包为 `meeting_harness/`，板端部署包实际为 `/userdata/meeting_agent/scripts/harness/`，启动命令是 `python3 -m harness.main`。

### 该次记录的完整链路（历史快照）

```text
L_R004S06C01.flac
-> sox 标准化为 mono / 16 kHz / 16-bit WAV
-> CPU/Torch 3D-Speaker diarization
-> padding / merge / 左右同 speaker 的短 unknown gap 吸收
-> segment plan + seg_*.wav
-> Qwen3-ASR 常驻 Batch runner
-> canonical [start,end,speaker,text] Timeline
-> Qwen3-4B ctx16k / rkllm3-server
-> 固定滑动章节窗口、全文摘要和待办复核
-> schema、refs、finish_reason 和截断校验
-> meeting_summary.json + meeting_frontend.json + meeting_display.txt（整批校验成功后发布）
```

板端完整测试入口：

```bash
cd /userdata/meeting_agent/scripts

python3 -m harness.main \
  --source-audio /userdata/meeting_agent/data/audio/L_R004S06C01.flac \
  --model-dir /userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k \
  --ctx 16384 \
  --predict 3072 \
  --max-tokens 3072 \
  --input-safety-tokens 512 \
  --input-chars-per-token 1.3 \
  --chunk-overlap-segments 1 \
  --out-dir /userdata/meeting_agent/output/harness_qwen3_4b_ctx16k \
  --ready-timeout 300 \
  --request-timeout 1200 \
  --overwrite
```

### Qwen3-4B ctx16k 已验证结果

本次完整 FLAC 测试已经确认 segmentation、Batch ASR、transcript prepare 和单次 16K LLM 请求成功。`rkllm3-server` 实际以 `-c 16384 -n 2048` 启动，`context_truncated=false`，server `return_code=0`。

```text
ctx / predict / max_tokens: 16384 / 2048 / 2048
prompt / completion / total: 10821 / 1561 / 12382 tokens
剩余上下文预算: 4002 tokens
server ready / request: 21.043s / 46.949s
prefill / decode: 545.919 / 57.941 tokens/s
segmentation / Batch ASR: 249.443s / 72.594s
```

内存结果：

```text
基线整板占用:          816.492 MB
整板峰值:             2680.770 MB
相对基线峰值增量:      1864.277 MB
最低 MemAvailable:    5233.578 MB
LLM summary 阶段峰值: 1273.535 MB
rkllm3-server HWM:     281.625 MB
```

该结果证明 Qwen3-4B 的 16K 模型可以在当前板端加载，并实际容纳本次 10821-token prompt 与 1561-token 输出。整板峰值主要来自 CPU/Torch 3D-Speaker，各阶段顺序加载和退出，内存峰值不叠加。

需要保留一个状态边界：截至该次历史运行，已确认 LLM HTTP 响应、usage、timings 和未截断状态，但尚未核对该次运行的 `validation.json` 与 `meeting_summary.json`。因此当时只能表述为“完整前处理、ASR 和 16K LLM 请求成功”，不能仅凭 HTTP 成功宣称最终会议纪要已通过 Harness 校验并发布；当前主线的验证状态见文档开头说明。

### Meeting Harness：thinking、滑动章节窗口与板端总结输出

Qwen3-4B ctx16k 最近一次完整会议请求为：

```text
prompt_tokens:      10922
completion_tokens:   1698
total_tokens:       12620
context_truncated:  false
```

模型输出包含 `<think>...</think>` 和其后的合法 JSON。thinking 会影响最终质量，因此 V2 不禁用思考模式，而是将默认输出预算提高到 `3072` tokens，并把原始正文、thinking 和 final JSON 分别保存。只有 final JSON 进入 schema/refs validation。

默认 16K 预算：

```text
ctx:                 16384
thinking + JSON:      3072
输入安全余量:           512
估算输入上限:         12800 tokens
字符/token 估算:        1.3（根据当前实测保守校准）
```

历史上下文策略（截至该次记录）：

```text
完整 Timeline 估算可放入预算
-> single_request_all_features
-> 一次生成全文摘要、章节速览、发言人总结和待办事项

完整 Timeline 超预算
-> 按完整 canonical segment 构造滑动章节窗口
-> completed_chapters 连续覆盖已结束内容
-> carryover_start_ref 将未结束话题带入下一窗口
-> 全部章节完成后生成全文摘要
-> 汇总原文证据，复核和去重待办候选
```

上述分流是历史实现。当前生产路径已统一固定使用滑动章节窗口，不再启用 `single_request_all_features`。

任何请求出现输入截断、thinking 未闭合、`finish_reason != stop`、非法 JSON 或 refs 校验失败，都不会进入最终发布。`--resume` 可以复用 segmentation、Batch ASR，以及 fingerprint 和产物 SHA-256 均匹配的已校验 LLM 请求；单次运行中的所有实时 LLM 请求只启动一次 `rkllm3-server`。

内部 `meeting_summary.json` 继续是事实源。校验和兼容导出成功后，Python 同批发布：

```text
meeting_frontend.json
meeting_display.txt
04_compat_export/transcription.json
04_compat_export/auto_chapters.json
04_compat_export/summarization.json
04_compat_export/meeting_assistance.json
04_compat_export/task_result.json
04_compat_export/manifest.json
```

参考格式兼容导出包含 `Transcription.Paragraphs`、`AutoChapters`、`ParagraphSummary`、`ConversationalSummary`、`Keywords`、`KeySentences` 和 `Actions` 等字段，仅用于对照和适配，不作为本项目或产品名称。当前 ASR 没有词级时间戳和真实姓名，因此一个 canonical segment 映射为一个 sentence/Words 单元，`SpeakerName` 暂时使用匿名 speaker ID，不虚构能力。

### Qwen3-8B ctx16k 状态

Qwen3-8B 已完成 RKNN3 v1.0.4 ctx16k 转换，四类部署文件 SHA-256 正确；但在 RK1828 上使用 `-c 8192` 和 `-c 16384` 均在 `rknn3_model_init / MODEL_SETUP` 阶段失败，未进入 HTTP 请求。Qwen3-4B ctx16k 重启后能正常运行，说明问题集中在 8B 产物的模型规模或板端 setup 兼容性。按当前决定不再继续该方向，本机转换脚本和 WSL 产物已清理，正式主线保留 Qwen3-4B ctx16k。

本文主要分为三部分：

第一部分为 **其他资源**，包括Rockchip提供了技术文档和仓库。

第二部分为 **目标**，介绍了本项目的目标。

第三部分为 **RK1828 的模型部署说明**，包括 RKNN3 Toolkit、Model Zoo、Runtime、模型转换、上板部署、版本限制。

第四部分为 **会议处理流程说明**，包括本地音频输入、ASR 转写、文本格式整理、长文本分段总结、JSON 输出和前端衔接方式。

第五部分为 **当前状态**，包括 SenseVoiceSmall ASR、Qwen2.5-7B 会议总结、Qwen3 lifelog 微调模型、本地/板端推理测试结果和后续方向。

第六部分为 **已知问题**，包括流程中常见的问题和部分问题的解决方案。

## 其他资源

### RK1828 文档

[V1.0.0 Quick Start](../Rockchip_RK182X_Quick_Start_RKNN3_SDK_V1.0.0_CN.pdf) 介绍如何使用RKNN3 Toolkit在PC端完成AI模型转换，并部署到搭载RK1820/1828协处
理器的Rockchip开发板上。

[V1.0.0 Release Note](../Rockchip_RK182X_ReleaseNote_RKNN3_SDK_V1.0.0_CN.pdf) 介绍V1.0.0支持的功能特性，支持的模型与其性能与精度。

[V1.0.4 Release Note](../Rockchip_RKNPU3_ReleaseNote_RKNN3_SDK_V1.0.4_CN.pdf) 介绍V1.0.4支持的功能特性，支持的模型与其性能与精度。

当前板端正式 runtime 已升级并验证为 v1.0.4。V1.0.0 手册与记录仅用于追溯早期转换和兼容性问题。

### 仓库和网盘

RKNN3 SDK 提供了将 AI 模型部署到 RK1820/RK1828/RK3572 所需的完整软件栈，包括：

[RKNN3-Toolkit](https://github.com/airockchip/rknn3-toolkit)：PC 端软件开发套件，支持模型转换、推理和性能评估等。

RKNN3 Runtime：板端运行时库，提供 C/C++ 编程接口，用于部署 RKNN 模型并加速 AI 应用。

[RKNN3 Model Zoo](https://github.com/airockchip/rknn3-model-zoo)：模型转换与部署示例仓库，包含 CNN / LLM / VLM 等多种模型的参考实现。

典型工作流程：用户首先在 PC 上使用 RKNN3-Toolkit 将训练好的模型转换为 RKNN 格式，然后通过 RKNN3 Runtime API 在开发板上进行推理。

Toolkit 与 Model Zoo 为公开仓库，Runtime 收费。

历史测试曾通过受控共享资源获取预转换 RKNN 模型和配套文件；访问方式和凭据不在仓库文档中保存。

## 目标

目前的方案是使用以下工作流，在rk1828计算板上测试小型本地模型：

会议音频 → 本地 ASR（自动语音识别）转录 → 带时间戳的转录文本 → 本地小型 LLM（大语言模型）摘要生成 → 会议摘要 / 总结 / 决议 / 行动事项

目前采用两步处理流程：ASR 模型：音频 → 文本 + 小型文本 LLM：转录文本 → 摘要

## RK1828 的模型部署说明

### 本地WSL工作目录：

```text
/root/Developer/Meeting_Agent/
├── docs/                         文档
├── meeting_harness/              正式会议 Agent Python Harness
├── prompts/                      Harness V1 Prompt 协议的可读版本
├── scripts/                      已验证板端脚本、评估工具和 local-only 实验
└── output/                       本机转换产物、实验产物、日志
```

`scripts/`

```text
 scripts/
  ├── README.md                              脚本索引
  ├── convert_qwen2_5_v100_ctx.sh            Qwen2.5 封装转换脚本，HF -> ONNX/config/tokenizer/embed -> RKNN/weight
  ├── export_qwen2_5_rknn_v100_ctx.py        Qwen2.5 RKNN 导出，设置 max_ctx_len
  ├── convert_qwen3_v100_ctx.sh              Qwen3 封装转换脚本，HF -> ONNX/config/tokenizer/embed -> RKNN/weight
  ├── export_qwen3_llm_v100.py               Qwen3 HF -> ONNX/config/tokenizer/embed
  ├── export_qwen3_rknn_v100_ctx.py          Qwen3 RKNN 导出，设置 max_ctx_len
  ├── rkllm_smoke_test.py                    板端 LLM 基础 smoke test
  ├── export_sensevoice_rknn_v100.py         SenseVoice ONNX -> RKNN/weight
  ├── test_sensevoice_asr.py                 SenseVoice CPU 参考、frontend 特征导出、RKNN 输入导出
  ├── prepare_sensevoice_stage1.py           SenseVoice Stage 1 最小板端验证包生成
  ├── mlx_lora_to_peft.py                    MLX LoRA adapter -> HF/PEFT adapter
  ├── merge_qwen3_lora.py                    LoRA merge 到 HF 基座模型
  ├── compare_lifelog_local.py               本地对比原版 Qwen3 与 lifelog 微调合并模型
  ├── archive/                               已完成的一次性板端测试脚本
  │   ├── rkllm_long_input_test.py           长输入测试
  │   ├── board_meeting_summary_strict_json.py  会议 JSON 总结测试
  │   ├── board_cascade_summary_7b_once.py   分段/滚动总结测试
  │   ├── test_rkllm_response_format.py      response_format 行为测试
  │   └── board_lifelog_real_test.py         Qwen3 lifelog merge 模型板端测试
  └── experiments/                           早期转换、训练、校准和模板实验脚本
      ├── export_qwen2_5_llm_eager_v100.py
      ├── export_qwen2_5_rknn_v100_ctx_default_kv.py
      ├── remove_qwen25_isnan_guard.py
      ├── build_lifelog_sft_dataset.py
      ├── build_lifelog_quant_dataset.py
      ├── train_qwen3_4b_lifelog_lora.py
      └── minimal_chatml_template.jinja
```

`output/` 为转换完毕的模型结果

### 板端

**重要信息**：

```text
登录：linaro@<board-host>
项目根目录：/userdata/meeting_agent
Harness：/userdata/meeting_agent/scripts/harness
启动入口：python3 -m harness.main
LLM server：/usr/bin/rkllm3-server
RKNN3 API：/usr/lib/librknn3_api.so
transfer proxy：/usr/bin/rknn3_transfer_proxy
runtime：1.0.4
板端内存：约 7.7 GiB
```

当前板端统一目录：

```text
/userdata/meeting_agent/
├── scripts/                            平铺板端脚本和 harness/
├── runtime/asr/qwen3_asr_gcc10/       Qwen3-ASR Batch runtime
├── models/asr/qwen3-asr-0.6b-rknn/    ASR 六类文件
├── models/llm/v104/                    v1.0.4 LLM 模型
├── data/audio/                         原始会议音频
├── input/                              其他输入
└── output/                             Harness、评估和性能结果
```

早期 `/userdata/qwen25-7b-ctx8k-v100/`、`/userdata/qwen3-4b-lifelog-real-ctx8k/` 和 `/userdata/v104_test/` 路径只属于历史记录，不再作为当前部署布局。

### LLM 转换流程

从hf源下载的模型文件需要先转换成onnx格式，然后转换为rknn格式。在 Release Note 有适配模型的列表，同时过程可以参考RK的Quick Start文档。
LLM 板端加载需要最终转换得到的四样文件：

- `.rknn`：图结构和模型元数据。
- `.weight`：量化后的主要权重文件。
- `.embed.bin`：embedding 权重。
- `.tokenizer.gguf`：tokenizer 文件。

#### Qwen2.5-7B 转换流程

Qwen2.5-7B-Instruct ctx8k为测试后可以在板端稳定运行并完成任务的模型。

可以使用现有的脚本 转换命令：

```bash
bash scripts/convert_qwen2_5_v100_ctx.sh \
  <hf_model_dir> \
  <output_dir> \
  <max_ctx_len>
```

| 参数位置         | 示例值                                   | 说明                                                |
| ---------------- | ---------------------------------------- | ------------------------------------------------- |
| `<hf_model_dir>` | `Qwen2.5-7B-Instruct`                    | Hugging Face 模型目录路径          |
| `<output_dir>`   | `output/rknn_ctx8192_qwen25_7b_instruct` | 转换后的 RKNN 模型输出目录                                 |
| `<max_ctx_len>`  | `8192`                                   | 模型的最大上下文长度，用于设置 `max_ctx_len` 参数 |


脚本首先调用 model-zoo 示例 rknn3-model-zoo/examples/Qwen2_5/python/export_llm.py，将HF 格式转换为 ONNX / config.pkl / tokenizer.gguf / embed.bin
然后调用本项目脚本 scripts/export_qwen2_5_rknn_v100_ctx.py，将ONNX + config.pkl 转换为 rknn + weight
同时显式设置 rknn.config(max_ctx_len=8192) 或者其他数值 会把模型支持的最大上下文上限写入 RKNN 模型配置，并影响 runtime 可分配的 KV cache 上限。

输出目录里应有：

```text
Qwen2.5-7B-Instruct-ctx8192-v100-eager-int4.rknn
Qwen2.5-7B-Instruct-ctx8192-v100-eager-int4.weight
Qwen2.5-7B-Instruct.embed.bin
Qwen2.5-7B-Instruct.tokenizer.gguf
```

### 板端启动

启动前先停止已有 server：

```bash
ssh linaro@<board-host> \
  "killall rkllm3-server 2>/dev/null || true"
```

启动模型

```bash
/usr/bin/rkllm3-server \
  -m <model_file> \
  --weight <weight_file> \
  --vocab <tokenizer_file> \
  --embed <embed_file> \
  -c <max_ctx_len> \
  -n <max_new_tokens> \
  --temp <temperature> \
  --top-k <top_k> \
  --top-p <top_p> \
  --repeat-penalty <repeat_penalty> \
  --host <host> \
  --port <port>
```

参数说明(Qwen2.5-7B-Instruct为例)：

| 参数                 | 示例值                                                                                 | 说明                                         |
| ------------------ | ----------------------------------------------------------------------------------- | ------------------------------------------ |
| `<model_file>`     | `/userdata/qwen25-7b-ctx8k-v100/Qwen2.5-7B-Instruct-ctx8192-v100-eager-int4.rknn`   | RKNN 模型文件                                 |
| `<weight_file>`    | `/userdata/qwen25-7b-ctx8k-v100/Qwen2.5-7B-Instruct-ctx8192-v100-eager-int4.weight` | 模型权重文件                                    |
| `<tokenizer_file>` | `/userdata/qwen25-7b-ctx8k-v100/Qwen2.5-7B-Instruct.tokenizer.gguf`                 | Tokenizer 文件                              |
| `<embed_file>`     | `/userdata/qwen25-7b-ctx8k-v100/Qwen2.5-7B-Instruct.embed.bin`                      | Embedding 文件                              |
| `<max_ctx_len>`    | `8192`                                                                              | Server 使用的最大上下文长度         |
| `<max_new_tokens>` | `1024`                                                                              | Server 单次请求允许生成的最大 Token 数                |
| `<temperature>`    | `0`                                                                                 | 采样温度，值越低输出越确定                             |
| `<top_k>`          | `1`                                                                                 | Top-K 采样参数，`1` 表示每步仅选择概率最高的 Token         |
| `<top_p>`          | `1`                                                                                 | Top-P（Nucleus Sampling）采样参数，`1` 表示不限制累计概率 |
| `<repeat_penalty>` | `1.05`                                                                              | 重复惩罚系数，用于降低重复生成内容的概率                      |
| `<host>`           | `0.0.0.0`                                                                           | Server 监听地址，`0.0.0.0` 表示允许局域网内其他设备访问      |
| `<port>`           | `8080`                                                                              | Server 监听端口                               |

`rkllm3-server` 用于加载 LLM，并启动一个 OpenAI API 兼容的 HTTP 服务。模型加载在 server 启动时完成。

```bash
curl http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "default",
    "messages": [
      {"role": "user", "content": "你好，简单介绍一下你自己。"}
    ],
    "temperature": 0,
    "max_tokens": 128
  }'
```

`-c` 指定 server 运行时启用的上下文窗口长度，不能超过模型转换时写入的 `max_ctx_len`。
`-n` 指定 server 侧允许生成的最大 token 数；请求中的 `max_tokens` 指定单次请求期望的最大输出 token 数。

## 会议处理流程说明

截至该历史记录，本地离线会议记录主线为：会议音频 -> CPU/Torch diarization -> Qwen3-ASR Batch 转写 -> canonical speaker Timeline -> Qwen3-4B ctx16k 单次完整输入 -> JSON 校验 -> 前端展示。ASR、LLM 和 diarization 按阶段顺序加载并退出；实测内存峰值不叠加，整板峰值来自 CPU/Torch 3D-Speaker。Qwen2.5-7B ctx8k 分段总结属于早期方案和对照基线。当前总结阶段已统一改为滑动章节窗口，详见 README 和架构说明。

### ASR流程

#### 音频预处理

目前输入音频统一转换为单声道16 kHz wav格式。多人会议流程中，预处理后再进入 VAD 和说话人识别。迁移到板子时，音频解码和重采样可以用任意本地库实现，但输出给 ASR 的音频格式建议保持稳定。

目前测试使用的数据集为：

单人：[中文多通道会议语音数据集AliMeeting](https://www.modelscope.cn/datasets/modelscope/AliMeeting)

多人：[AISHELL-4 多通道中文会议开源语音数据库](https://www.aishelltech.com/newsinfo/2226596.html)

#### ASR

当前 ASR 主线是 Qwen3-ASR-0.6B 的常驻 Batch runner。正式输入来自 3D-Speaker 生成的 mono、16 kHz、16-bit PCM `seg_*.wav`，130 段实测耗时约 72 秒。SenseVoiceSmall 和固定 chunk 方案仅作为早期实验与对照，不再是正式主线。

ASR 输出包含转写文本、片段起止时间和匿名 speaker。多人会议的当前流程是：音频格式调整 -> CPU/Torch 3D-Speaker -> padding / merge / unknown fallback -> 切 segment WAV -> Qwen3-ASR Batch 转写 -> 合成 `segment_transcripts.json` 和 canonical Timeline。最终应保留以下语义：

### 文本总结流程

转写文本作为LLM的总结输入

#### 输出策略

当前正式入口是 `meeting_harness`。它使用 `segment_transcripts.json` 生成带稳定 `segment_id`、时间戳和 speaker 的 canonical Timeline，再让 LLM 输出带证据引用的 JSON：

```json
{
  "title": "会议标题或 null",
  "overview": {
    "text": "会议整体概述",
    "refs": ["seg-000001"]
  },
  "chapters": [
    {
      "title": "章节标题",
      "overview": "章节概述",
      "speaker_ids": ["speaker_A"],
      "start_ms": 1000,
      "end_ms": 9000,
      "refs": ["seg-000001", "seg-000002"]
    }
  ],
  "speakers": [
    {
      "speaker_id": "speaker_A",
      "overview": "该发言人的主要贡献",
      "refs": ["seg-000001"]
    }
  ],
  "key_points": [{"text": "关键要点", "refs": ["seg-000001"]}],
  "decisions": [{"text": "明确决定", "refs": ["seg-000002"]}],
  "action_items": [
    {
      "task": "明确提出的后续事项",
      "owner": "speaker_A 或 null",
      "deadline": "原文明确出现的截止时间或 null",
      "refs": ["seg-000001"]
    }
  ],
  "open_questions": [],
  "risks": [],
  "keywords": [{"keyword": "关键词", "refs": ["seg-000001"]}]
}
```

章节时间和参与 speaker 由 Python Harness 根据 refs 确定性回填。无事实的标量使用 `null`，无事实的集合使用 `[]`，不再用“未明确”“暂无”等占位字符串。

#### Prompt

该历史快照当时使用的是早期 Prompt 协议；当前可读协议位于 `prompts/meeting_summary_v32_zh.md`，运行时以 `meeting_harness/llm.py` 和 `meeting_harness/product_summary.py` 中的内嵌版本为准。当前运行时 Prompt 和固定滑动窗口口径以根目录 README、`docs/architecture.md` 及主线代码为准。核心约束包括：

- 只根据 canonical Timeline 生成纪要，不编造事实。
- 只输出合法 JSON，不输出 Markdown、解释或思考过程。
- 所有重要语义条目必须引用真实且文本非空的 `segment_id`。
- speaker、负责人和截止时间必须有原文依据；没有依据时返回 `null`。
- 普通讨论不能升级为决策或待办。
- `finish_reason` 不是 `stop`、输入被截断或 schema/refs 校验失败时，不发布最终纪要。

截至该历史快照，Harness 同时保留完整上下文和滑动章节窗口路径。长会议使用 carryover 驱动的自然章节窗口，并在全部章节完成后单独执行 full-summary 和 action-review；发言人总结在滑动路径中按 speaker batch 独立处理。当前生产路径已统一固定使用滑动章节窗口；Qwen3-4B ctx16k 仍使用 compact r/sp ID、章节范围确定性归并、章节重叠兜底、full-summary refs 自动合并和 speaker 超预算截断。

### ASR RKNN 转换命令

当前 RKNN 导出脚本：scripts/export_sensevoice_rknn_v100.py

静态 600 帧导出命令格式：

```bash
<python> \
  scripts/export_sensevoice_rknn_v100.py \
  --onnx-path <onnx_model> \
  --rknn-path <rknn_model> \
  --max-feats <max_feats>
```

| 参数             | 示例值                                                                  | 说明                                                             |
| -------------- | -------------------------------------------------------------------- | -------------------------------------------------------------- |
| `<python>`     | `/root/Developer/test/miniconda3/envs/rknn_v100_official/bin/python` | Python 路径。 |
| `<onnx_model>` | `output/sensevoice_small_onnx/model.onnx`                            | 输入的 ONNX 模型路径。                                                 |
| `<rknn_model>` | `output/sensevoice_small_onnx/SenseVoiceSmall-fp-static600.rknn`     | 导出的 RKNN 模型路径。                                                 |
| `<max_feats>`  | `600`                                                                | 模型支持的最大输入特征帧数，对应导出时固定的输入长度。                    |


该脚本内部设置：

```python
rknn.config(target_platform="rk1820", core_num=1)
rknn.load_onnx(
    model=onnx_path,
    inputs=["speech", "speech_lengths", "language", "textnorm"],
    input_size_list=[[1, 600, 560], [1], [1], [1]],
)
rknn.build(do_quantization=False)
rknn.export_rknn(rknn_path)
```

- 当前是 fp/static600 版本，没有做量化。
- `600` 是特征帧长度上限，对应约 30 秒以内短音频特征。
- 如果音频更长，需要在应用层做 VAD/切片，再逐段推理。

## 当前状态

本文开头的“2026-08-12 历史方案快照”只代表当时状态：Qwen3-ASR Batch 是 ASR 主线，Qwen3-4B ctx16k 已完成未截断的完整会议 LLM 请求验证。以下 SenseVoice、Qwen2.5 ctx8k/ctx16k 和 lifelog 内容为历史实验记录；当前生产路径统一使用滑动章节窗口和 4096-token 输出预算。

**SenseVoiceSmall ASR（历史）** 已完成早期本地验证。

项目中已准备 `SenseVoiceSmall/` 原始模型目录，并通过 FunASR 跑通 CPU 参考推理、测试音频转写和frontend 特征导出。当前已转换出 RKNN3 static600 模型主体。现阶段ASR 的主要阻塞是缺少 RKNN3 C/C++ runner 开发所需的 `rknn3_api.h`、`float16.h`，因此还不能编译板端 ASR runner。

**Qwen2.5-7B-Instruct ctx8k（历史基线）** 已完成转换、上板和基础验证，曾作为会议总结主线。

该模型已完成 smoke test、长输入会议总结测试、`response_format` 行为测试和分段/滚动总结方案验证。实际测试中，7B 比此前尝试的 3B/4B 更稳，更适合中文会议纪要、决策和行动项整理。但 ctx8k 仍无法一次性覆盖较长会议转写，实际可用窗口还要扣除 prompt、JSON schema 和输出 tokens；JSON 格式对上下文和输出长度都有明显开销，因此长会议应采用“带重叠的分段总结 + 汇总合并 + 后端 JSON 校验/修复”的流程。

**Qwen2.5-7B-Instruct ctx16k（历史探索）** 已尝试转换，用于探索更长上下文能否直接处理更长会议转写。该模型的失败不能泛化为 Qwen3-4B ctx16k 不可运行；后者已经完成 12382-token 未截断请求。

目前结论是 ctx16k 的转换和运行成本明显高于 ctx8k：7B 模型在 16k 上下文下需要约 96GB 级别内存，并会产生较大的临时文件；板端加载、运行内存占用和长输入稳定性仍需继续验证。因此 ctx16k 暂不作为当前主线，ctx8k + 分段总结仍是更稳妥的方案。

### Qwen3-4B / lifelog 微调模型结果

**Qwen3-4B lifelog 微调模型** 已完成本地 adapter 检查、MLX LoRA 到 HF/PEFT 的转换、LoRA merge 和本地推理对比。

本地测试表明，微调模型相比原版 Qwen3-4B 有明显的优势：在完整转写输入下，微调版使用训练时 prompt，可在 474 个生成 token 内输出完整合法 JSON，内容更紧凑，待办和决策更贴近任务定义。

因此，LoRA微调可以带来优化，但目前 merge LoRA + w4a16 量化的版本上板后，微调行为明显退化。见已知问题 *LoRA支持*

### 当前阻塞点

主要的问题：
1. [缺少 RKNN3 C/C++ runner 所需的开发头文件](https://github.com/airockchip/rknn3-toolkit/issues/4)。LLM 可以通过 `rkllm3-server` 提供的服务层直接加载并提供 OpenAI-compatible API，因此不需要自行编写推理程序。ASR 没有现成的 server 封装，需要自行编译 runner。当前 SenseVoiceSmall 模型虽然已经转换完成，但由于缺少 `rknn3_api.h` 以及对应 API 文档，暂时无法编译和验证。之后可以参考的流程是完成音频解码、frontend、VAD 和多段拼接部分，最后把 ASR 输出接入 Qwen2.5-7B ctx8k 分段总结流程。网盘中提供了V1.0.5b2的动态链接库与头文件。但无法确定修改了什么内容，很可能存在不兼容的问题。
2. V1.0.0 下没有可用的 LoRA runtime adapter 挂载流程，微调模型如前文所说 merge 的方案效果不好，根据Relase Note，可能需要升级到 SDK V1.0.4 或更高。

## 已知问题

### 官方模型 ctx2048

官方提供的[预转换模型](https://console.box.lenovo.com/l/H1fig1)，包含板端所需的所有文件，但多为上下文长度2048，不能满足会议记录总结的输入长度需求。其他长度模型要自己参考第二部分的模型转换流程重新转换，并设置 `max_ctx_len`控制上下文长度。

### 型转换时的资源分配

onnx到rknn转换时转换时需注意内存分配，对于7B参数模型，8k上下文需要内存约48GB，16k则需要约96GB，同时会在tmp/ 下生成40-50GB左右的临时文件。整个过程耗时较长。

### 加载时 `max_ctx_len` 与输出长度不同

转换时：

```python
rknn.config(max_ctx_len=8192)
  # 转换阶段写入模型支持的最大上下文长度上限。
  # 也会影响 runtime 可分配的 KV cache 上限。
```

加载时：

```bash
rkllm3-server -c 8192 -n 1024
  # -c: server 运行时使用的上下文窗口大小，不能超过模型转换时的 max_ctx_len。
  # -n: server 默认/上限生成 token 数，控制最长输出长度。
```

请求时：

```json
{"max_tokens": 1024}
```

三者要配合控制实际的输入、输出长度。

### LoRA 支持

V1.0.0 当前没有可用的 runtime LoRA adapter 挂载流程。需要升级sdk到V1.0.4：

注意文本格式、prompt需要和LoRA说明保持一致。

### 多人会议ASR没有区分发言人

ASR 前增加 diarization。转写文本必须保留 speaker 标签。LLM Prompt 明确要求按发言人整理。

### SenseVoiceSmall 加载
SenseVoiceSmall模型主体已经转换出 RKNN3 产物，但模型加载需要的C++ runtime development package 缺失。.

### JSON格式

当前板端 `rkllm3-server` 上的 `POST /v1/chat/completions` 接口支持 `response_format: {"type": "json_object"}` 参数。但在实际测试中，该参数不能作为严格 JSON 保证；具体而言它无法完全避免输出被 `max_tokens` 截断、字段类型漂移、前后多余文本、括号未闭合或内容编造等问题。因此仍必须在后端做校验。

## 历史推进记录

以下按日期保留当时结论。路径、runtime 和主线模型可能已被本文开头的当前方案替代。

### 2026-08-07 项目推进更新

当前项目主线已经从早期 SenseVoiceSmall / 固定 chunk ASR 测试，推进到 RK1828 板端完整会议链路 baseline。现阶段推荐链路为：

```text
原始会议音频
-> CPU/Torch 3D-Speaker diarization
-> padding / merge / unknown fallback
-> segment plan + seg_*.wav
-> Qwen3-ASR NPU 分段识别
-> [start,end,speaker,text] timeline
-> LLM 会议纪要 JSON
```

关键结论：

- Qwen3-ASR-0.6B 是当前 ASR 主线，已在 RK1828 板端通过官方 RKNN3 runner 跑通；
- 3D-Speaker CPU/Torch 版是当前 speaker diarization 主线，完整 36m50s 音频约 4 分钟完成，speaker 聚类与 TextGrid 对齐较好；
- 3D-Speaker 的 FSMN VAD 和 CAMPPlus 已做过 RKNN/NPU 可运行性验证，但 CAMPPlus RKNN embedding 在完整 pipeline 中导致 speaker 聚类退化为 1 个 speaker，因此暂不作为正式主线；
- 当前允许 Python diarization 作为板端前处理模块存在，后续 C++/RKNN/RKLLM 链路通过文件接口消费 segment plan 和切分音频；
- 板端已完成一版完整 ASR baseline，可生成 `[start,end,speaker,text]` timeline，并与 TextGrid 生成可读对比文件。

当前完整会议测试结果：

```text
音频: L_R004S06C01.flac，约 36m50s
CPU diarization prepare: 约 4m01s
ASR segments: 194
ASR success_count: 194
ASR failed_count: 0
ASR empty_text_count: 24
ASR total_elapsed_seconds: 1254.738s
CER vs TextGrid time-sorted GT: 0.159178
```

speaker / coverage 结果：

```text
pred_speaker_count: 7
ref_speaker_count: 7
raw RTTM speaker_accuracy_on_overlap: 0.995952
segment plan known_speaker_accuracy_on_overlap: 0.997595
known_speech_recall: 0.943745
all_speech_recall_with_unknown: 1.0
```

当前主要输出目录：

```text
/userdata/meeting_agent/output/segment_prepare_cpu_full
/userdata/meeting_agent/output/segment_asr_cpu_full
/userdata/meeting_agent/output/segment_asr_cpu_full/textgrid_eval
```

可读对比文件：

```text
gt_timeline.txt                      TextGrid GT 时间线
asr_timeline_mapped.txt              ASR 时间线，预测 speaker 映射到 GT speaker
asr_timeline_mapped_with_empty.txt   包含空文本段的 ASR 时间线
asr_gt_segment_overlap_preview.txt   每个 ASR segment 与重叠 GT 文本的肉眼对比
```

当前主要问题是 unknown 段数偏多：

```text
unknown_segment_count: 64 / 194 ≈ 33%
unknown duration ratio: 约 7.21%
unknown GT speech overlap ratio: 约 5.63%
unknown ASR char ratio: 约 5.91%
```

虽然 unknown 按时长和文本量占比不高，但按段数约三分之一，会影响 timeline 可读性和 LLM 输入质量。下一阶段重点是减少短碎 unknown、处理 padding 边界重复、清洗 timeline，然后再接 LLM 会议纪要生成和质量评估。

### 2026-08-10 项目推进更新

当前已完成短 unknown 吸收方案和新版完整 ASR baseline。新方案仅吸收左右为同一个 speaker、且不超过 2 秒的未覆盖区间，不依赖 ASR 文本判断 speaker。

结果对比：

```text
unknown segment: 64 -> 32
总 ASR segment: 194 -> 130
known speech recall: 94.37% -> 95.76%
known speaker accuracy: 99.76% -> 99.74%
known segment purity: 97.67% -> 98.03%
all speech recall: 保持 100%
```

新版 Qwen3-ASR 全量结果：

```text
segment_count: 130
success_count: 130
failed_count: 0
empty_text_count: 12
ASR elapsed: 858.735s，约 14m19s
```

相较旧版 20m55s，耗时降低约 31.6%，空文本段减半，整体文本量变化较小。当前正式测试目录为：

```text
/userdata/meeting_agent/output/segment_prepare_cpu_absorb_unknown_2s
/userdata/meeting_agent/output/segment_asr_cpu_absorb_unknown_2s
```

完整文本人工检查确认：ASR 可以较好保留会议主题和一级内容，但存在少量高影响语义错误，主要集中在否定关系、数字、专业术语和责任对象。例如：

```text
不可以 -> 可以
不安全因素 -> 安全因素
建议系好安全带 -> 切勿系好安全带
1.8 米 -> 18 米
三分之二 -> 三分之一
```

这些错误主要出现在 20～30 秒正常 segment 中，并非短音频导致，更可能是当前板端 ASR 模型能力、远场音质和专业词汇识别限制。由于暂时没有更合适的板端 ASR 模型，当前问题先记录，不继续阻塞项目推进。

下一阶段正式转向 LLM 会议总结验证：使用新版带时间戳和 speaker 的 transcript 生成会议纪要 JSON，重点评估主题覆盖、speaker 观点归纳，以及 LLM 是否会放大 ASR 中的否定、数字和专业词错误。

### 2026-08-10 Batch ASR runner 更新

后续板端 segment ASR 正式切换到常驻 batch runtime：

```text
/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo
```

输入仍为 diarization 预处理生成的 mono、16 kHz、16-bit PCM `seg_*.wav`。正式 Python 入口为 `scripts/board/board_segment_asr_batch.py`，它会自动生成 C++ runner 所需的无表头 `job_id<TAB>wav_path` 清单，一次加载模型处理全部音频，再输出原有评估和 LLM 链路可直接读取的 `segment_transcripts.json/csv` 与 `llm_input_timeline.txt`。

130 段板端实测：

```text
completed: 130
ok: 118
transcript_empty: 12
elapsed: 71.109s，约 1m11s
```

此前逐段启动模型耗时为 858.735 秒；常驻 batch runner 约加速 12.08 倍。`transcript_empty` 是已完成但无有效文本的音频段，不视为执行崩溃。后续不再使用旧逐段 runner 作为正式执行路径。

### 2026-08-11 8K 上下文与全流程内存基线

使用板端已有的 Qwen2.5-7B v100 ctx8k 模型，在 v104 `rkllm3-server` 上完成了真实 8192-token 输入测试：

```text
n_ctx_slot: 8192
原始 prompt: 9291 tokens
实际处理 prompt: 8192 tokens
prefill: 14944.023 ms
prompt speed: 548.18 tokens/s
```

该请求不是短输入 smoke test，KV cache 已实际填充到 8K。内存结果：

```text
请求前整机占用: 953.398 MB
请求期间整机峰值: 1126.941 MB
8K 请求额外峰值: 173.543 MB
rkllm3-server RSS 峰值: 233.340 MB
最低可用内存: 6787.406 MB
```

同时完成原始会议音频到 LLM 的顺序全流程资源测试：

```text
原始 FLAC
-> CPU/Torch 3D-Speaker + 2 秒短 unknown 吸收
-> Batch ASR
-> ctx8k LLM
```

阶段耗时和整机峰值：

```text
3D-Speaker: 245.534s
Batch ASR: 71.809s
满 8K LLM prefill: 14.944s
全流程整机峰值: 2665.691 MB，约 2.60 GiB
```

各阶段顺序加载和退出，因此内存峰值不叠加，整条 pipeline 取各阶段最大值。板端总内存约 7.73 GiB，当前 8K 全流程仍有约 5 GiB 余量。因此 8K 尚未达到 Linux 可见内存上限，全流程峰值主要来自 CPU/Torch 3D-Speaker，而不是 LLM。

需要区分：该结果证明 8K 在 Linux 可见内存上余量充足，但不能单独证明 NPU 设备侧可以创建任意更大的 KV cache。已有 7B ctx16k 模型在 `rknn3_create_mem` / `MODEL_SETUP` 阶段失败，说明还需确认长上下文模型的转换配置和 NPU buffer 限制。

已通过 SHA-256 确认 WSL ctx8k 构建产物与板端实际跑通的模型完全一致。可运行 ctx8k 模型的转换参数为：

```text
kvcache_buffer_len: 8192
max_position_embeddings: 8192
kvcache_dtype: Int4_to_F16
kvcache_store_method: GroupQuant
kvcache_group_size: 16
kvcache_residual_depth: 64
```

下一步严格沿用该配方，只将 `kvcache_buffer_len` 与 `max_position_embeddings` 同时改为 32768，生成 Qwen2.5-7B v104 ctx32k 探索模型，用于测试板端上下文上限。ctx32k 测试属于资源和 NPU 能力探索；该历史记录中的正式会议 pipeline 曾由 harness 根据实际 token 预算决定使用完整输入还是分段，当前生产路径已统一固定使用滑动章节窗口。
