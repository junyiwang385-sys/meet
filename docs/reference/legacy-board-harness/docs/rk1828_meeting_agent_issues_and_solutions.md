# RK1828 会议转写与总结：问题、实验与解决方案

> **历史调试记录。** 本文保留 diarization、ASR、长上下文、NPU、LLM 和 Harness 的实验过程与失败证据。文中的“当前方案”“下一步”和机器路径只代表对应测试日期，可能已被后续实现替代。现行入口见 [项目 README](../README.md)，运行机制见 [架构说明](architecture.md)。

本文重点记录长音频 ASR 完整度、speaker 区分、长上下文 LLM，以及结构化会议纪要的阶段性结论和问题定位。保留旧观察是为了复现实验和避免重复踩坑，不应将其直接解释为当前生产配置。

> **当前主线：** 运行时固定使用 `sliding_chapter_windows`，不再使用一次性全量总结。ASR、canonical Timeline 和 RTTM/segment 后处理沿用现有链路不变。当前主线已在 30 个样本上完成板端验证，其中包括前 10 组和后 20 组复用既有 ASR 结果的运行。

## 2026-08-12 Qwen3-4B 16K 历史基线快照

### 当时的正式环境（历史快照）

```text
WSL：/root/Developer/Meeting_Agent
RK1828：linaro@<board-host>
板端根目录：/userdata/meeting_agent
板端 Harness：/userdata/meeting_agent/scripts/harness
启动入口：cd /userdata/meeting_agent/scripts && python3 -m harness.main
完整音频：/userdata/meeting_agent/data/audio/L_R004S06C01.flac
```

Windows 到 WSL 由 WSL 主动 `scp` 拉取；WSL 到板端统一使用 `rsync --bwlimit=10m`。

### 如何证明 16K 实际生效

不能只看模型目录名或转换脚本参数，至少需要同时核对以下证据：

1. `03_llm_summary/llm_cmd.json` 中实际 server 命令包含 `-c 16384 -n 2048`；
2. `run_config.json` 中 `ctx / predict / max_tokens` 为 `16384 / 2048 / 2048`；
3. `03_llm_summary/server_status.json` 中 `context_truncated=false`；
4. HTTP response 的 usage 记录实际 token；
5. server 正常退出，`return_code=0`。

本次结果：

```text
prompt_tokens:      10821
completion_tokens:   1561
total_tokens:       12382
remaining context:   4002
context_truncated:  false
server return_code: 0
```

因此可以确认，本次完整 Timeline 和输出实际使用了 12382-token 预算，没有被截断。这里的剩余 4002 token 按 `16384 - 12382` 计算，是本次 prompt 与 completion 合计后的窗口余量。

性能：

```text
server ready: 21.043s
request:      46.949s
prefill:      19821.620 ms，545.919 tokens/s
decode:       26941.049 ms，57.941 tokens/s
```

### 完整顺序链路内存

```text
segmentation:                 249.443s
Batch ASR:                     72.594s
transcript prepare:             0.020s
baseline board used:          816.492 MB
board used peak:             2680.770 MB
board peak delta:            1864.277 MB
minimum MemAvailable:        5233.578 MB
LLM summary board peak:      1273.535 MB
rkllm3-server HWM:            281.625 MB
```

各阶段按顺序加载和退出，内存峰值不叠加。当前整板峰值主要来自 CPU/Torch 3D-Speaker，而不是 16K LLM。

### LLM 请求成功与 Harness 最终成功的边界

`response.json` 存在、usage 正常、`context_truncated=false` 只能证明 LLM 请求成功。`meeting_harness/pipeline.py` 只有在 `validate_llm_result()` 通过后才会写出：

```text
03_llm_summary/validation.json
meeting_summary.json
meeting_result.json: status=ok
stage_status.json: status=succeeded
```

如果 `meeting_summary.json` 不存在，应优先查看：

```bash
python3 -m json.tool <out-dir>/stage_status.json
python3 -m json.tool <out-dir>/meeting_result.json
python3 -m json.tool <out-dir>/03_llm_summary/validation.json
cat <out-dir>/03_llm_summary/response_summary_content.txt
```

截至该次历史运行，已确认完整前处理、Batch ASR、Timeline 和 16K LLM 请求成功，但当时的 validation 与最终纪要发布状态尚未核对。因此不能把该次运行写成“完整 Harness 已成功发布会议纪要”；后续 30 个样本的板端验证已补充当前状态。

### 长上下文结论

早期 Qwen2.5-7B ctx16k 在 `rknn3_create_mem` / `MODEL_SETUP` 阶段失败，只能证明该具体模型和转换配置不可用，不能泛化为 RK1828 上所有 16K 模型均不可运行。Qwen3-4B ctx16k 已经提供了反例：模型可加载，完整请求可执行，且总 token 达 12382。

长上下文状态必须分层记录：

```text
1. 脚本准备完成
2. 转换产物完成并校验
3. 板端模型 setup / server ready 成功
4. 实际长输入请求成功且未截断
5. Harness validation 与兼容导出通过，并同批发布 meeting_summary.json、meeting_frontend.json、meeting_display.txt
```

Qwen3-4B ctx16k 已确认模型 setup、完整长输入请求和 thinking 后合法 JSON 输出；此前板端旧 Harness 因未剥离 `<think>` 而在 validation 阶段失败。在该历史快照中，Harness 同时保留完整上下文一次总结和长会议滑动章节窗口；当前生产路径统一固定为滑动章节窗口，并保留断点续跑、板端可读文本和参考格式兼容导出。Qwen3-8B ctx16k 已完成转换和四文件校验，但在 `-c 8192` 与 `-c 16384` 下均于 `MODEL_SETUP` 失败，当前停止该方向。

### Meeting Harness 长上下文处理

Harness 保持 Qwen3 thinking 开启，默认使用 `ctx=16384`、`predict/max_tokens=4096` 和 512-token 输入安全余量，对应启发式输入预算为 11776 tokens。当前生产路径无论 Timeline 长短，都按完整 canonical segment 构造滑动章节窗口，使用 `carryover_start_ref` 保留未结束话题，全部章节完成后再生成全文摘要并复核待办，再通过 speaker batches 生成发言人总结。所有实时 LLM 请求只启动一次 `rkllm3-server`，`--resume` 只复用 fingerprint 和产物哈希均匹配的已校验请求。

内部 evidence-linked `meeting_summary.json` 是事实源；成功后确定性生成 `meeting_frontend.json`、可直接 `cat` 的 `meeting_display.txt`，以及参考格式兼容的 `Transcription.Paragraphs`、`AutoChapters`、`ParagraphSummary`、`ConversationalSummary`、`KeySentences` 和 `Actions`。当前没有词级时间戳和真实姓名，不做虚构映射。

目标链路：

```text
会议音频 -> speaker/time 分析 -> 分段 ASR -> [start,end,speaker,text] -> LLM -> 会议纪要 JSON
```

---

## 1. 当前已确认的基础状态

### LLM 与板端服务

- v104 Qwen2.5-3B、Qwen2.5-7B、Qwen3-4B 模型文件已通过 checksum 验证，内容完整。
- v104 Qwen2.5-7B 已经在板端跑通：

```text
Qwen3-ASR -> rkllm3-server -> Qwen LLM -> summary JSON
```

- `rkllm3-server` 曾卡在 `rknn3_init`，结论是 RKNN3 / NPU transfer proxy 状态异常，不是模型文件问题；重启板端后恢复。

后续如果 LLM server 再次长时间不 ready，优先检查：

```bash
pgrep -af rknn3_transfer_proxy
pgrep -af rkllm3-server
ss -lntp | grep 18231
free -h
```

### Qwen3-ASR demo 的定位

Qwen3-ASR 当前通过官方 C/C++ runner 调用：

```text
rknn_qwen3_asr_demo
```

它负责音频读取、解码、前处理、RKNN 推理和后处理。模型文件本身不能单独运行。

当前 demo 输出主要是：

```text
text res: ...
```

即纯文本，不直接输出 speaker，也不直接输出句级/词级时间戳。

---

## 2. 长音频 ASR 当前方案

### FLAC 与 WAV

Qwen3-ASR demo 理论上支持 FLAC 解码，实测原始 FLAC 可以被读取。但原始 8ch 长 FLAC direct 输出明显不完整。

当前测试音频：

```text
L_R004S06C01.flac：8ch / 16kHz / 约 36m50s
```

direct 原始 FLAC 一次性送入 Qwen3-ASR 时，转写文本只约为 TextGrid 参考文本的 11%，因此不能作为长会议主方案。

FLAC 转 WAV 本身不是有损压缩，真正会改变信息的是：

```text
8ch -> mono
```

因此原始 8ch FLAC 应保留作为母版；mono WAV 是当前 ASR 和 diarization 的稳定工作格式。

### 长音频切片

官方 demo 有单次输入时长限制，真实会议需要应用层切片。当前已验证可行的 ASR 主线是：

```text
原始长音频
-> sox 标准化为 mono 16k 16-bit PCM WAV
-> 按 chunk 完整切片
-> 每个 chunk 调 Qwen3-ASR offline demo
-> 拼接 transcript
```

在 `120s chunk` 下，36m50s 音频可完整覆盖为 19 段，转写文本长度约为 GT 的 89%，内容覆盖从开场到结尾。该方案适合作为长音频 ASR 完整度基线。

但固定 chunk 不是最终最优切分方式。后续 speaker 版本会转向：

```text
speaker/time segment -> 分段 ASR
```

而不是固定 120s 硬切。

---

## 3. TextGrid GT 与评估方式

TextGrid 是当前数据集的人工标注，包含：

```text
speaker tier
start time
end time
text
```

可抽象为：

```json
{"start": 3.74, "end": 4.81, "speaker": "001-M", "text": "零零幺"}
```

注意：TextGrid 文件本身按 speaker tier 存储，不是全局时间线顺序。用于会议全文和 LLM 输入时，必须抽取所有非空 interval 后按时间排序。

之前 CER 偏高，主要原因是 reference 按 tier 顺序拼接，导致文本顺序错乱。后续 ASR 准确率评估应使用：

```text
TextGrid interval -> 按 start/end 全局排序 -> reference_time_sorted -> 再算 CER/token error rate
```

---

## 4. speaker 区分需求与总体路线

当前先做匿名 speaker 区分：

```text
speaker_0 / speaker_1 / speaker_2 ...
```

暂不做真实身份识别：

```text
speaker_0 -> 李总 / 王工
```

原因是身份识别需要声纹注册样本和声纹库，当前实际需求暂不具备。

已排除/暂不采用：

- **channel-based speaker**：实际会议不会给每个人独立麦克风，不能依赖通道和人的对应关系。
- **LLM 猜 speaker**：LLM 可用于总结和少量 unknown 的上下文推理，但不应作为 speaker 判断主模块。
- **直接重写 Qwen3-ASR demo**：ASR demo 只负责转文字，不能解决 speaker diarization 的核心问题。

当前推荐路线：

```text
整段音频
-> 3D-Speaker diarization
-> RTTM: [start,end,speaker]
-> 覆盖率检查 / padding / unknown 兜底
-> segment plan
-> 按 segment 切音频
-> Qwen3-ASR 转写每段
-> 合成 [start,end,speaker,text]
-> 按时间线输入 LLM
```

---

## 5. 3D-Speaker 测试结论

### 输入与输出

3D-Speaker 现成 pipeline 当前不直接接受该 FLAC，需先转为：

```text
mono / 16kHz / 16-bit PCM WAV
```

3D-Speaker 输出 `.rttm`，只包含时间段和 speaker，不包含文本：

```text
SPEAKER <audio_id> 0 <start> <duration> <NA> <NA> <speaker_id> <NA> <NA>
```

等价于：

```json
{"start": 3.810, "end": 5.685, "speaker": "0"}
```

### speaker 区分效果

用 RTTM 与 TextGrid 对比后：

- 预测 speaker 数：7；
- TextGrid speaker 数：7；
- 在双方都检测到语音的区间，speaker 匹配准确率约 99.6%；
- speaker 聚类/区分能力目前看是可用的。

### 主要问题：漏检

默认 RTTM 覆盖不足明显，尤其集中在 `005-F` 的部分长句，不是简单的“嗯/啊”等无关短语。因此不能直接按默认 RTTM 切音频，否则会丢会议内容。

当前判断：

```text
speaker 可以 unknown，但内容不能漏。
```

因此优先级应是：

```text
先保证语音覆盖完整度
再优化 speaker 标签准确性
最后接 ASR 和 LLM
```

---

## 6. padding 与漏检测试结论

当前测试方法：

1. 从 TextGrid 读取 GT 的 `[start,end,speaker,text]`；
2. 从 RTTM 读取 3D-Speaker 的 `[start,end,speaker]`；
3. 计算每个 GT interval 被 RTTM 覆盖的比例；
4. coverage 低的 GT interval 被视为漏检或覆盖不足；
5. missed report 中的文本来自 TextGrid GT，不是 ASR 输出。

padding 只是扩展 RTTM 时间边界，不是合并：

```text
[start,end] -> [start-pad,end+pad]
```

它用于模拟后续切 ASR 时多切一点边界，弥补 VAD/diarization 边界偏紧的问题。

当前结果：

```text
pad 0.0s: missed_seconds ≈ 324s，missed_ratio ≈ 16.0%
pad 0.5s: missed_seconds ≈ 105s，missed_ratio ≈ 5.2%
pad 1.0s: missed_seconds ≈ 60s，missed_ratio ≈ 2.9%
```

结论：

- padding 对覆盖率提升非常明显，说明很多漏检来自边界偏紧；
- 仍有少量真实漏检，主要集中在 `005-F` 局部；
- 后续不应直接丢弃这些区间，应使用 unknown segment 兜底。

设计上应区分两套时间：

```json
{
  "start": 10.0,
  "end": 14.0,
  "asr_start": 9.0,
  "asr_end": 15.0,
  "speaker": "speaker_1"
}
```

- `start/end`：speaker 时间，用于显示、对齐和 LLM 输入；
- `asr_start/asr_end`：实际切给 ASR 的时间，可带小 padding。

---

## 7. 音频切分与 ASR 合并逻辑

由于 Qwen3-ASR 不输出时间戳，不能先跑完整 ASR 再把文本直接分配给 speaker。当前最直接可行的方式是反过来：

```text
先按 speaker/time segment 切音频
再对每段音频 ASR
```

示例：

```text
3D-Speaker:
[01:00-03:00] speaker_1
[03:00-04:00] speaker_2
[04:00-04:30] speaker_3
[04:30-05:00] speaker_1
```

切成四段 WAV：

```text
seg_001.wav -> speaker_1
seg_002.wav -> speaker_2
seg_003.wav -> speaker_3
seg_004.wav -> speaker_1
```

分别送 Qwen3-ASR，最终合成：

```text
[01:00-03:00][speaker_1] ...
[03:00-04:00][speaker_2] ...
[04:00-04:30][speaker_3] ...
[04:30-05:00][speaker_1] ...
```

注意：不是把某个 speaker 全场所有发言合成一个音频。只合并时间上相邻、间隔很短、同 speaker 的片段，避免破坏会议时序。

---

## 8. 后处理与 unknown 兜底策略

RTTM 原始段数较多，不能每个小段都直接 ASR。需要生成适合 ASR 的 segment plan。

推荐后处理：

```text
1. 合并相邻同 speaker 的小 gap 片段
2. 给 ASR 输入时间加小 padding
3. 太短片段合并或保留为短段
4. 太长片段再拆分，避免单段 ASR 过长
5. 检查未覆盖区间，补 speaker=unknown
```

unknown 的作用是保证内容不丢：

```json
{"start": 1070.3, "end": 1081.9, "speaker": "unknown", "text": "..."}
```

LLM 可以在总结阶段根据上下文弱推理 unknown 属于谁，但系统不应强行把 unknown 标成某个 speaker。

---

## 9. LLM 输入格式建议

最终给 LLM 的主输入应按时间线排序，而不是按 speaker 分组。

推荐：

```text
[00:03.74-00:04.81][speaker_0] ...
[00:04.95-00:05.71][speaker_1] ...
```

原因是会议纪要依赖上下文推进、回应关系和结论形成过程。按 speaker 分组会破坏时序。

按 speaker 分组可以作为辅助信息，用于生成“各发言人观点”，但不应替代时间线 transcript。

---

## 10. 当前脚本

当前已使用/新增的关键脚本：

```text
scripts/board_meeting_chain_profile.py
scripts/board_asr_eval_common.py
scripts/board_asr_direct_flac_eval.py
scripts/board_asr_standard_wav_eval.py
scripts/compare_diarization_textgrid.py
scripts/diarization_missed_intervals.py
```

作用简述：

- `board_meeting_chain_profile.py`：板端 ASR -> LLM 全链路与内存采样；
- `board_asr_direct_flac_eval.py`：原始 FLAC direct ASR 评估；
- `board_asr_standard_wav_eval.py`：mono WAV chunk ASR 评估；
- `compare_diarization_textgrid.py`：RTTM 与 TextGrid speaker 对比；
- `diarization_missed_intervals.py`：导出 TextGrid 中被 RTTM 漏检/覆盖不足的 interval。

---

## 11. 当前阶段结论

1. LLM 与 Qwen3-ASR 基础链路已跑通。
2. 原始 8ch FLAC direct ASR 不完整，长音频必须做应用层切分。
3. 固定 120s mono WAV chunk 可作为 ASR 完整度基线，但不是 speaker 版本最终切分方式。
4. Qwen3-ASR 只输出文本，不输出 speaker 或精确时间戳。
5. 3D-Speaker 可输出 speaker/time，speaker 区分效果很好，但默认覆盖率不足。
6. padding 可显著改善 RTTM 覆盖率，但仍需要 unknown 兜底避免内容丢失。
7. 最终目标是生成按时间排序的 `[start,end,speaker,text]` transcript，再交给 LLM。

---

## 12. 下一步建议

短期优先：

1. 做 padding 参数扫描，同时重新计算 speaker accuracy / precision / recall，选择合适 padding。
2. 设计并生成 segment plan：合并同 speaker、小 gap、padding、长段拆分、unknown 兜底。
3. 先不接 LLM，先用 segment plan 切音频，跑 Qwen3-ASR，生成第一版 `[start,end,speaker,text]`。
4. 与 TextGrid 按时间线对比，评估内容完整度和 speaker/text 质量。

后续优化：

1. 若 unknown 或漏检仍多，考虑调 VAD 或叠加更宽松 VAD，而不是优先换整个模型。
2. 若 3D-Speaker 在更多数据上覆盖率不稳定，再对比 FunASR / pyannote 等 pipeline。
3. 若最终需要板端化，再拆分 VAD / CAM++ embedding / clustering，评估 CPU/NPU 资源占用。

---

## 13. 板端 3D-Speaker / CAMPPlus + FSMN VAD NPU 转换测试记录

当前 3D-Speaker 已经在 RK1828 板端 CPU 环境跑通。早期曾因短音频测试中初始化、下载、`mp.spawn` 重复加载等固定开销占比过高，误判为 CPU 方案不可用；后续完整 36m50s 音频实测表明，CPU/Torch 版 diarization 约 4 分钟完成，speaker 聚类准确率高，可以作为当前稳定主方案。RKNN/NPU 方向仍完成了模型可运行性和轻量接入验证，但 CAMPPlus embedding RKNN 版在完整聚类中出现 speaker 聚类退化，暂不作为正式主线。

当前板端 speaker 相关 ModelScope 模型已整理到：

```text
/userdata/meeting_agent/models/spk/modelscope/models/
```

核心模型包括：

```text
VAD:
iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/.../model.pt

CAMPPlus / CAM++ speaker embedding:
iic--speech_campplus_sv_zh_en_16k-common_advanced/.../campplus_cn_en_common.pt
```

3D-Speaker 的整体逻辑不能直接整体转成 RKNN。应拆成：

```text
适合上 NPU：
- FSMN VAD 模型
- CAMPPlus / CAM++ speaker embedding 模型

继续 CPU：
- 音频切窗口
- fbank/feature 前处理
- clustering
- RTTM 后处理
- padding / merge / unknown fallback
- segment plan
- 切 WAV
```

### CAMPPlus 当前测试结果

CAMPPlus 已完成第一轮 NPU 可行性验证：

```text
PyTorch .pt
-> ONNX
-> RKNN3 1.0.4 .rknn + .weight
-> 板端 RKNN3 runtime 1.0.4 推理成功
```

ONNX 导出使用 3D-Speaker 自带脚本：

```text
speakerlab/bin/export_speaker_embedding_onnx.py
```

导出的 ONNX 输入输出为：

```text
input:  feature   [batch_size, frame_num, 80]
output: embedding [batch_size, 192]
```

这说明 CAMPPlus 输入不是原始 WAV，而是 CPU 前处理后的 80 维声学特征。当前为了最小验证，RKNN 转换时固定输入为：

```text
[1, 150, 80]
```

其含义是：一次处理一个约 1.5s 语音窗口的 fbank 特征。该长度对应 3D-Speaker diarization 中的默认 embedding 切分：

```python
def chunk(self, st, ed, dur=1.5, step=0.75)
```

也就是 1.5s 窗口、0.75s 滑动步长。

RKNN3 转换环境与板端 runtime 均为 1.0.4：

```text
WSL toolkit: rknn3-toolkit 1.0.4
板端 runtime: librknn3_api version 1.0.4
```

CAMPPlus 转换产物为双文件，不是单 `.rknn`：

```text
/userdata/meeting_agent/models/spk/campplus_cn_en_common_fp.rknn
/userdata/meeting_agent/models/spk/campplus_cn_en_common_fp.weight
```

板端官方工具验证命令：

```bash
unset LD_LIBRARY_PATH

/usr/bin/rknn3_model_test \
  /userdata/meeting_agent/models/spk/campplus_cn_en_common_fp.rknn \
  /userdata/meeting_agent/models/spk/campplus_cn_en_common_fp.weight
```

验证结果：

```text
rknn3_load_model_from_data success
rknn3_model_init success
input:  feature [1, 150, 80], dtype=FP16
output: embedding [1, 192], dtype=FP16
model run cost: 约 5.284 ms
All 1 loops completed successfully
```

因此当前可以确认：

```text
CAMPPlus / CAM++ speaker embedding 模型可以在 RK1828 NPU 上运行。
```

### FSMN VAD 当前测试结果

FSMN VAD 也已完成第一轮 NPU 可行性验证：

```text
PyTorch .pt
-> FunASR 官方 ONNX export_meta 导出 model.onnx
-> RKNN3 1.0.4 .rknn + .weight
-> 板端 RKNN3 runtime 1.0.4 推理成功
```

VAD 原始模型：

```text
/root/.cache/modelscope/models/iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/snapshots/v2.0.4/model.pt
```

FunASR VAD ONNX 导出时需要注意：当前 FunASR 1.4.1 仍使用 `dynamic_axes`，在较新的 PyTorch ONNX exporter 下会报 `Failed to convert 'dynamic_axes' to 'dynamic_shapes'`。本次验证通过 monkey patch `torch.onnx.export(..., dynamo=False)` 强制走 legacy exporter 后导出成功。

导出的 ONNX 输入输出为：

```text
inputs:
- speech    [1, feats_length, 400]
- in_cache0 [1, 128, 19, 1]
- in_cache1 [1, 128, 19, 1]
- in_cache2 [1, 128, 19, 1]
- in_cache3 [1, 128, 19, 1]

outputs:
- logits     [1, feats_length, 248]
- out_cache0 [1, 128, 19, 1]
- out_cache1 [1, 128, 19, 1]
- out_cache2 [1, 128, 19, 1]
- out_cache3 [1, 128, 19, 1]
```

其中 `speech` 的 400 维来自 VAD 配置：`n_mels=80`、`lfr_m=5`，即 80 维 mel 特征做 5 帧拼接。cache 长度来自 `lorder + rorder - 1 = 20 + 0 - 1 = 19`。

ONNXRuntime 随机输入验证通过：

```text
speech [1,30,400]
in_cache0~3 [1,128,19,1]
logits output shape: [1,30,248]
out_cache0~3 output shape: [1,128,19,1]
finite: True
```

RKNN3 转换时固定输入为：

```text
speech:    [1, 30, 400]
in_cache*: [1, 128, 19, 1]
```

RKNN3 转换产物同样为双文件：

```text
/userdata/meeting_agent/models/spk/fsmn_vad_streaming_fp.rknn
/userdata/meeting_agent/models/spk/fsmn_vad_streaming_fp.weight
```

板端官方工具验证命令：

```bash
unset LD_LIBRARY_PATH

/usr/bin/rknn3_model_test \
  /userdata/meeting_agent/models/spk/fsmn_vad_streaming_fp.rknn \
  /userdata/meeting_agent/models/spk/fsmn_vad_streaming_fp.weight
```

板端验证结果：

```text
rknn3_load_model_from_data success
rknn3_model_init success
input speech [1, 30, 400], dtype=FP16
input in_cache0~3: RKNN input attr 显示为 [1, 8, 19, 1, 16], layout=NC1HWC2, dtype=FP16
output logits [1, 30, 248], dtype=FP16
output out_cache0~3 [1, 128, 19, 1], dtype=FP16
model run cost: 约 0.691 ms
All 1 loops completed successfully
```

因此当前可以确认：

```text
FSMN VAD 模型可以在 RK1828 NPU 上运行。
```

### 完整 pipeline 轻量接入测试记录

板端当前保留了一个 RKNN 轻量接入版本：

```text
/userdata/3D-Speaker/speakerlab/bin/infer_diarization_rknn.py
```

已完成的主要改动：

```text
- CAMPPlus PyTorch checkpoint 不再加载，embedding 推理改为调用 campplus_rknn_batch_runner；
- FSMN VAD 的 ComputeScores() 被 monkey patch，encoder logits/cache 改为调用 fsmn_vad_rknn_sequence_runner；
- nprocs == 1 时不再 mp.spawn，避免单进程场景下父子进程重复初始化；
- RKNN VAD FP16 输出遇到极小值下溢为 0 时，FunASR 后处理的 math.log(sum_score) 会报 math domain error，已在 scores_np 读回后加 1e-12 下限保护。
```

相关本地/板端脚本与 runner：

```text
本机归档（不纳入 Git）：scripts/local_only/rknn_diarization_experiments/campplus_rknn_batch_runner.cpp
本机归档（不纳入 Git）：scripts/local_only/rknn_diarization_experiments/fsmn_vad_rknn_sequence_runner.cpp
本机归档（不纳入 Git）：scripts/local_only/board_patches/patch_infer_diarization_rknn_*.py
本机归档（不纳入 Git）：scripts/local_only/legacy/board_3dspeaker_segment_prepare.py

板端历史 binary：/userdata/meeting_agent/runtime/spk/rknn3/bin/campplus_rknn_batch_runner
板端历史 binary：/userdata/meeting_agent/runtime/spk/rknn3/bin/fsmn_vad_rknn_sequence_runner
```

需要注意：当前 3D-Speaker RKNN 版仍会初始化 FunASR VAD pipeline 并加载一次 VAD `model.pt`，这是为了复用 FunASR 的 frontend、cache 结构和 VAD 后处理状态机。实际 VAD encoder 推理由 RKNN runner 接管，日志中出现以下行时说明 patch 生效：

```text
[INFO]: Patched FSMN VAD encoder with RKNN runner.
```

### RKNN 版与 CPU/Torch 版完整音频对比

测试音频：

```text
/userdata/meeting_agent/data/audio/L_R004S06C01.flac
8ch / 16kHz / 约 36m50s，board prepare 脚本统一转 mono 16k WAV 后再送入 3D-Speaker。
```

统一 segment prepare 参数：

```text
--pad 1.0
--known-merge-gap 0.5
--unknown-min-gap 0.5
--unknown-merge-gap 0.5
--max-known-segment 30
--max-unknown-segment 20
```

完整音频耗时对比：

```text
RKNN 版：
prepare 总耗时约 2m04.8s
3D-Speaker diarization 子进程 elapsed 约 118.3s
Rank 0 processing 约 84.0s

CPU/Torch 版：
prepare 总耗时约 4m01.3s
3D-Speaker diarization 子进程 elapsed 约 234.8s
Rank 0 processing 约 158.3s
```

这里的 `prepare` 指完整说话人切段准备阶段，不只是模型推理，包含：

```text
原始 FLAC -> sox 转 mono16k WAV -> 3D-Speaker diarization -> RTTM
-> padding -> known merge/split -> unknown gap fallback -> segment_plan -> 切 seg_*.wav
```

完整音频输出对比：

```text
RKNN 版：
raw_rttm_segments: 476
known_segments_after_merge_split: 115
unknown_segments_after_merge_split: 72
total_asr_segments: 187
plan_union_covered_ratio: 1.0
raw RTTM speaker: 仅 0 一个 speaker，约 1564.27s

CPU/Torch 版：
raw_rttm_segments: 468
known_segments_after_merge_split: 130
unknown_segments_after_merge_split: 64
total_asr_segments: 194
plan_union_covered_ratio: 0.999833
raw RTTM speaker: 0~6 共 7 个 speaker
```

CPU/Torch 版与 TextGrid 对齐结果：

```text
pred_speaker_count: 7
ref_speaker_count: 7
speaker_accuracy_on_overlap: 0.995952
speech_precision: 0.989402
speech_recall: 0.792401
```

含义：3D-Speaker 原版只要检出语音，speaker 聚类基本正确；默认 RTTM 的主要问题仍是语音覆盖率偏低。通过后续 `padding + unknown gap fallback`，segment plan 覆盖率接近 1，可以保证“speaker 可 unknown，但内容不直接丢”。

### 当前结论

当前正式主线调整为：

```text
原始 FLAC
-> CPU/Torch 3D-Speaker diarization
-> padding / merge / unknown fallback
-> segment_plan + seg_*.wav
-> Qwen3-ASR NPU 批量识别
-> [start,end,speaker,text]
-> LLM 总结
```

原因：

```text
- CPU/Torch 版完整 36m50s 音频约 4 分钟跑完，效率可接受；
- CPU/Torch 版 speaker 数与 TextGrid 一致，overlap speaker accuracy 约 99.6%；
- RKNN 版虽然速度约快 1.9 倍，但 CAMPPlus embedding 接入后聚类退化为 1 个 speaker，不能作为正式 diarization 主线；
- RKNN VAD encoder 单独看大概率可用，VAD 检段数量和语音总时长与 CPU 接近；主要问题集中在 CAMPPlus RKNN embedding 与 Torch embedding 的距离结构不一致。
```

工程上允许 Python diarization 作为独立前处理子进程存在，后续 C++/RKNN/RKLLM 链路通过文件接口消费其产物：

```text
input_mono16k.wav
3dspeaker_out/*.rttm
segment_plan/segment_plan.json
cut_audio/cut_segments.csv
cut_audio/wav_segments/seg_*.wav
```

### 后续建议

短期不继续卡 CAMPPlus RKNN，对会议链路优先采用 CPU/Torch 3D-Speaker，继续推进 ASR 批量转写和 LLM 纪要。

如果后续仍要优化 speaker embedding 到 NPU，需要先做数值对齐，而不是只验证 runner 能运行：

```text
1. dump 同一批 3D-Speaker fbank feats；
2. 分别跑 Torch CAMPPlus、ONNX CAMPPlus、RKNN CAMPPlus；
3. 比较单条 embedding cosine similarity / L2 norm；
4. 比较 pairwise cosine distance matrix；
5. 最终再看 RTTM speaker 数和 TextGrid speaker accuracy。
```

只有 embedding 距离结构与 Torch 版足够一致时，才重新考虑 CAMPPlus RKNN 作为正式方案。

---

## 14. 板端 CPU diarization + Qwen3-ASR 全量 timeline 基线

当前已经完成第一版板端完整会议转写 baseline。正式采用 CPU/Torch 3D-Speaker 作为 diarization 前处理，随后用 Qwen3-ASR NPU runner 对切分后的 `seg_*.wav` 批量识别。

板端主要输出目录：

```text
segment prepare:
/userdata/meeting_agent/output/segment_prepare_cpu_full

ASR batch:
/userdata/meeting_agent/output/segment_asr_cpu_full

ASR vs TextGrid eval:
/userdata/meeting_agent/output/segment_asr_cpu_full/textgrid_eval
```

### segment plan 结果

完整音频 `L_R004S06C01.flac` 约 36m50s，CPU/Torch 3D-Speaker + padding / merge / unknown fallback 后结果为：

```text
audio_duration: 2210.35s
raw_rttm_segments: 468
known_segments_after_merge_split: 130
unknown_segments_after_merge_split: 64
total_asr_segments: 194
plan_union_covered_ratio: 0.999833
```

与 TextGrid 对齐后的关键指标：

```text
known_speech_recall: 0.943745
all_speech_recall_with_unknown: 1.0
known_speaker_accuracy_on_overlap: 0.997595
```

含义：known speaker 段 speaker 基本准确；unknown fallback 负责兜住 3D-Speaker 未覆盖或覆盖不足的 GT 语音，避免直接丢内容。

### Qwen3-ASR 分段识别结果

对 194 个 segment wav 全量识别结果：

```text
segment_count: 194
success_count: 194
failed_count: 0
empty_text_count: 24
total_text_chars: 8271
total_elapsed_seconds: 1254.738s
Finished marker count: 0
```

注意：Qwen3-ASR demo 对静音/空段有时会输出 `Finished` 边界标记。当前已在 `board_segment_asr_batch.py` 的提取后处理里过滤该 marker，避免进入 transcript。

### ASR 与 TextGrid 文本评估

当前使用：

```text
scripts/diarization/evaluate_segment_asr_with_textgrid.py
```

对 `segment_transcripts.json` 和 TextGrid 做评估。TextGrid 路径：

```text
/userdata/meeting_agent/output/spk_diarization/L_R004S06C01.TextGrid
```

板端运行示例：

```bash
/userdata/miniforge3/envs/3dspeaker/bin/python \
  /userdata/meeting_agent/scripts/evaluate_segment_asr_with_textgrid.py \
  --segments /userdata/meeting_agent/output/segment_asr_cpu_full/segment_transcripts.json \
  --textgrid /userdata/meeting_agent/output/spk_diarization/L_R004S06C01.TextGrid \
  --out-dir /userdata/meeting_agent/output/segment_asr_cpu_full/textgrid_eval
```

机械指标结果：

```text
asr_text_chars: 8440
gt_text_chars: 8547
normalized ASR chars: 7442
normalized GT chars: 7344
char_distance: 1169
CER: 0.159178
unknown CER: 0.871362
```

CER 表示字符错误率，只能作为粗略机械指标。当前更重要的是看语义是否符合会议内容，因此脚本新增了可读 timeline 输出。

### 可读 timeline 输出

评估脚本会额外生成：

```text
gt_timeline.txt
asr_timeline_mapped.txt
asr_timeline_mapped_with_empty.txt
asr_gt_segment_overlap_preview.txt
```

含义：

```text
gt_timeline.txt:
[index][start-end][GT speaker] GT文本

asr_timeline_mapped.txt:
[index][start-end][GT speaker(pred:预测speaker)] ASR文本

asr_gt_segment_overlap_preview.txt:
按每个 ASR segment 展示 ASR 文本、时间重叠 GT 文本、同 speaker GT 文本。
```

示例查看：

```bash
head -n 40 /userdata/meeting_agent/output/segment_asr_cpu_full/textgrid_eval/gt_timeline.txt
head -n 40 /userdata/meeting_agent/output/segment_asr_cpu_full/textgrid_eval/asr_timeline_mapped.txt
head -n 80 /userdata/meeting_agent/output/segment_asr_cpu_full/textgrid_eval/asr_gt_segment_overlap_preview.txt
```

当前肉眼初步判断：

```text
- speaker 映射基本正常，例如 pred:3 -> 004-M，pred:5 -> 001-M；
- 工厂安全、高处作业、安全帽、反光背心、校园安全等主题基本识别到；
- 存在局部错字和语义细节偏差，例如“劳动密集性”识别成“活动危险密集型”；
- padding 会导致 segment 边界文本重复或跨 speaker；
- 开头多人编号段高度重叠，不适合作为整体质量判断依据。
```

### unknown 问题

当前 unknown 占比：

```text
unknown_segment_count: 64 / 194 ≈ 33%
unknown duration: 约 159.42s / 2210.35s ≈ 7.21%
unknown overlap GT speech: 约 114.0s / 2026.5s ≈ 5.63%
unknown ASR chars: 约 499 / 8440 ≈ 5.91%
```

虽然 unknown 按时长和文本量占比不高，但按段数约三分之一，会明显影响 timeline 可读性和后续 LLM 输入质量。后续优化重点应从“保证内容不漏”转向“减少短碎 unknown”：

```text
1. 合并相邻短 unknown；
2. 对很短、夹在同一 speaker 附近的 unknown，尝试归并到邻近 speaker；
3. 调整 unknown_min_gap / unknown_merge_gap；
4. 在进入 LLM 前过滤空文本 unknown 和明显噪声文本；
5. 保留覆盖率评估，避免优化 unknown 时重新丢失 GT 内容。
```

---

## 15. 短 unknown 吸收与新版 ASR baseline

为减少短碎 unknown 和 ASR runner 的重复启动开销，新增了从原始音频重新处理的板端脚本：

```text
scripts/board/board_3dspeaker_segment_prepare_absorb_unknown.py
```

该脚本不修改旧 CSV，也不使用 ASR 文本判断 speaker，而是重新执行：

```text
原始 FLAC/WAV
-> mono 16k WAV
-> CPU/Torch 3D-Speaker
-> padding
-> 找出未覆盖 gap
-> 将“左右为同一 speaker 且时长不超过 2 秒”的 gap 吸收到该 speaker
-> 其余 gap 保留 unknown
-> 重新切分 WAV
```

### unknown 吸收结果

完整音频实测：

```text
raw_rttm_segments: 466
unknown_gap_count_before: 85
unknown_gap_seconds_before: 156.80s
absorbed_unknown_count: 54
absorbed_unknown_seconds: 40.04s
remaining_unknown_count_after_split: 32
remaining_unknown_seconds: 116.76s
known_segments_after_absorption_split: 98
total_asr_segments: 130
plan_union_covered_ratio: 1.0
```

54 个被吸收 gap 全部满足左右 speaker 相同，平均时长约 0.74 秒，最长 1.98 秒。未吸收的 gap 主要包括：

```text
over_threshold: 23
左右 speaker 不同: 6
leading_gap: 1
trailing_gap: 1
```

与旧 baseline 对比：

| 指标 | 旧方案 | 新方案 |
|---|---:|---:|
| known segment | 130 | 98 |
| unknown segment | 64 | 32 |
| 总 ASR segment | 194 | 130 |
| unknown 时长 | 159.42s | 116.76s |
| known speech recall | 0.943745 | 0.957562 |
| all speech recall | 1.0 | 1.0 |
| known speaker accuracy | 0.997595 | 0.997423 |
| known speaker purity | 0.976744 | 0.980264 |

结论：unknown 段数减少 50%，总 ASR 调用次数减少约 33%，已知语音召回率提高，同时 speaker accuracy 基本不变，known segment purity 略有提高。2 秒的同 speaker gap 吸收规则可以作为当前新 baseline。

### 新版 ASR 实测结果

使用新生成的 130 个 segment WAV 重新运行 Qwen3-ASR：

```text
segment_count: 130
success_count: 130
failed_count: 0
empty_text_count: 12
total_elapsed_seconds: 858.735s，约 14m19s
```

与旧版对比：

| 指标 | 旧方案 | 新方案 |
|---|---:|---:|
| ASR 段数 | 194 | 130 |
| 空文本段 | 24 | 12 |
| ASR 耗时 | 1254.738s | 858.735s |
| timeline 文本字符 | 8440 | 8264 |
| unknown 文本字符 | 499 | 357 |

ASR 耗时降低约 31.6%，空文本段减半，timeline 文本量仅下降约 2.1%。新版主要输出目录：

```text
/userdata/meeting_agent/output/segment_prepare_cpu_absorb_unknown_2s
/userdata/meeting_agent/output/segment_asr_cpu_absorb_unknown_2s
/userdata/meeting_agent/output/segment_asr_cpu_absorb_unknown_2s/textgrid_eval
```

### 正式切换常驻 Batch ASR runner

后续 segment ASR 不再使用每段重新启动一次模型的官方 demo，正式 runtime 切换为：

```text
/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo
```

可执行文件：

```text
rknn_qwen3_asr_batch_demo
```

runner 接口已经通过板端实际执行确认：

```text
rknn_qwen3_asr_batch_demo \
  <encoder.rknn> <encoder.weight> \
  <llm.rknn> <llm.weight> \
  <llm.tokenizer.gguf> <llm.embed.bin> \
  <audio_core_mask> <llm_core_mask> \
  <manifest.tsv> <results.jsonl>
```

`manifest.tsv` 无表头，每行格式为：

```text
job_id<TAB>/absolute/path/to/segment.wav
```

输入音频由正式预处理链路生成，要求为 mono、16 kHz、16-bit PCM WAV。当前顺序为：

```text
原始 FLAC/WAV
-> mono 16 kHz PCM WAV
-> CPU/Torch 3D-Speaker
-> padding
-> 左右同 speaker 且不超过 2 秒的 unknown gap 吸收
-> known 最长 30 秒、unknown 最长 20 秒切段
-> batch runner 常驻加载模型并处理全部 segment
```

130 段实测：

```text
BATCH_DONE jobs=130 completed=130 failed=12 elapsed=71.109 exit=1
status: ok=118, transcript_empty=12
results.jsonl: 130 行
```

这里 runner 的 `failed=12` 和 `exit=1` 是因为它将空转写记为 `transcript_empty`，并非模型初始化、音频读取或推理崩溃。包装脚本将 `ok` 和 `transcript_empty` 都视为已完成结果，真正失败只统计音频读取失败、推理错误或结果缺失。

与此前逐段启动模型的 130 段 baseline 相比：

| 指标 | 旧逐段 runner | 新常驻 batch runner |
|---|---:|---:|
| segment | 130 | 130 |
| 有文本 | 118 | 118 |
| 空文本 | 12 | 12 |
| 总耗时 | 858.735s | 71.109s |
| 加速 | 1.0x | 约 12.08x |

后续正式入口为：

```text
scripts/board/board_segment_asr_batch.py
```

该脚本自动校验 WAV 格式、从 `seg_*.wav` 与 `cut_segments.csv` 生成 runner TSV、运行 C++ batch demo，并继续输出原有评估和 LLM 链路需要的：

```text
segment_transcripts.json/csv
batch_asr_summary.json
llm_input_timeline.txt
llm_input_timeline_with_empty.txt
```

### 8K 上下文与全流程资源实测

板端已有 Qwen2.5-7B v100 ctx8k 模型已在 v104 `rkllm3-server` 上完成真实满上下文测试。输入来自当前完整 pipeline 新生成的 ASR timeline：

```text
timeline lines: 124
timeline characters: 13073
UTF-8 bytes: 29383
原始 prompt: 9291 tokens
实际 prompt: 8192 tokens
n_ctx_slot: 8192
```

日志明确记录：

```text
slot init: n_ctx_slot = 8192
new prompt: n_prompt_tokens = 9291
input truncated: n_ctx = 8192
最终 n_prompt_tokens = 8192
```

因此本次不是约 2K token 的分段调用，而是真实填满 8K KV cache 的 prefill 请求。资源结果：

| 指标 | ctx8k 实测 |
|---|---:|
| prefill 时间 | 14.944s |
| prefill 速度 | 548.18 token/s |
| 请求前整机占用 | 953.398 MB |
| 请求期间整机峰值 | 1126.941 MB |
| 请求额外峰值 | 173.543 MB |
| server RSS 峰值 | 233.340 MB |
| 最低可用内存 | 6787.406 MB |

原始音频到 LLM 的顺序全流程也已完成资源采样：

```text
CPU/Torch 3D-Speaker: 245.534s
常驻 Batch ASR: 71.809s
整条 pipeline 整机峰值: 2665.691 MB，约 2.60 GiB
```

3D-Speaker、ASR、LLM 按阶段顺序执行并退出，内存峰值不会相加，整条 pipeline 使用各阶段最大值。当前 8K 全流程在约 7.73 GiB 的板端内存上仍有明显余量，峰值主要来自 CPU/Torch 3D-Speaker。

### 长上下文模型转换问题与后续验证

已确认 v104 Toolkit 官方 Qwen2.5 `export_rknn.py` 未显式指定 context 时使用默认配置。Toolkit 1.0.4 源码中的默认 attention/KV cache 配置包括：

```text
kvcache_buffer_len: 1024
kvcache_dtype: Float16
kvcache_store_method: Normal
kvcache_group_size: 32
kvcache_residual_depth: 32
max_position_embeddings: 8192
```

旧 v100 ctx16k 构建日志记录的长上下文参数为：

```text
kvcache_buffer_len: 16384
max_position_embeddings: 32768
kvcache_store_method: GroupQuant
kvcache_dtype: Int4_to_F16
kvcache_group_size: 16
kvcache_residual_depth: 64
```

但“编译成功”不等于“板端可运行”。现有 v100 7B ctx16k 在板端出现：

```text
rknn3_create_mem timeout
MODEL_SETUP fail / segmentation fault
```

失败后 NPU runtime 状态会异常，导致已知可用 ctx2048 模型也无法及时启动；板端重启后 ctx2048 在约 35 秒内恢复正常。因此后续长上下文测试每次失败后都应先恢复或重启 NPU 环境，再测其他模型。

已通过 SHA-256 确认 WSL ctx8k 构建产物与板端实际跑通的模型完全一致。该模型的已验证转换参数为：

```text
kvcache_buffer_len: 8192
max_position_embeddings: 8192
kvcache_store_method: GroupQuant
kvcache_dtype: Int4_to_F16
kvcache_group_size: 16
kvcache_residual_depth: 64
```

当时的决策：8K 尚未达到 Linux 可见内存上限，下一目标直接探索 32K。v104 ctx32k 将严格沿用上述配置，只把 `kvcache_buffer_len` 和 `max_position_embeddings` 同时改为 32768。32K 的目标是测量 NPU/setup/context 上限，而不是直接作为正式会议模型；该历史记录中的正式 pipeline 曾由 harness 根据 token 数决定完整输入或分段，当前生产路径已统一固定使用滑动章节窗口。

### ASR 完整文本语义检查

完整 ASR 与 TextGrid GT 的人工语义检查表明：

```text
- 会议主题结构基本完整：工地、校园、食品、餐厅、消防、家庭、驾车、旅游安全均被识别；
- speaker 和 unknown 已不再是当前最大问题；
- 当前 ASR 可以较好回答“会议谈了什么”；
- 但不能稳定回答“具体应该怎么做”，尤其是数字、否定、专业术语和责任关系。
```

已确认约 8 个明确的关系反转点，分布在 7 个约 20～30 秒的 segment 中，并非主要由短音频造成。代表性问题：

```text
“警示区没有封闭、留有缺口” -> “有封闭、没有缺口”
“这样都不可以” -> “这样都可以”
“不安全因素” -> “安全因素”（3 处）
“爆胎原因很多” -> “爆胎原因不多”
“建议全程系好安全带” -> “切勿全程系好安全带”
```

还存在数字和专业术语错误：

```text
“一点八米” -> “十八米”
“三分之二处” -> “三分之一处”
“动火监护人” -> “综合监护人”
“防回火装置” -> “防火围护装置”
“报告给主管处理”识别后责任对象丢失
```

这些问题大概率来自当前 Qwen3-ASR-0.6B 在远场会议、单声道混音、弱读否定音节和专业词汇上的能力限制。当前没有更合适的板端 ASR 模型，因此暂不继续阻塞 ASR 优化，先在最终 LLM 总结结果中观察实际影响。

### 当前阶段决策

当前将新版 diarization + ASR 结果作为 LLM 输入 baseline，下一阶段转向会议总结验证：

```text
segment_asr_cpu_absorb_unknown_2s
-> 时间线文本清洗 / 边界重复处理
-> rkllm3-server
-> 会议纪要 JSON
-> 与 GT 会议内容人工对比
```

LLM 评估时应区分：

```text
1. 主题概览是否完整；
2. 各 speaker 的主要观点是否正确；
3. 是否因 ASR 否定、数字或专业词错误生成错误结论；
4. 是否出现模型自行补全或编造具体安全规范；
5. 最终纪要是否适合作为会议记录，而不是未经核验的权威安全操作指南。
```
