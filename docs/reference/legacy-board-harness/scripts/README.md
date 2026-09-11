# Scripts Index

本目录只记录仓库中正式跟踪的脚本。生产总入口是 `meeting_harness.main`（板端部署名通常为 `harness.main`），不是任意单个 profile 或诊断脚本。

```text
scripts/
├── board/          Harness 直接依赖与板端诊断
├── diarization/   diarization、TextGrid、segment 和 ASR 分析
└── local_only/    本机一次性实验；由 Git 忽略
```

旧实验实现已从当前代码树删除，必要时通过 Git 历史查看，不再维护 `scripts/old/`。

## 生产依赖

### `board/board_3dspeaker_segment_prepare_absorb_unknown.py`

正式 segmentation 入口：

```text
source audio
-> SoX mono / 16 kHz / 16-bit PCM
-> CPU/Torch 3D-Speaker
-> RTTM padding / merge
-> 左右同 speaker 的短 unknown 吸收
-> unknown fallback
-> segment plan + seg_*.wav
```

由 Harness 通过 subprocess 调用。

### `board/board_segment_asr_batch.py`

正式 Batch ASR 入口。它生成 C++ runner 使用的无表头 TSV，一次加载 Qwen3-ASR 模型处理全部 segment WAV，并输出：

```text
manifest.tsv
results.jsonl
batch_runner.log
batch_asr_summary.json
segment_transcripts.json/csv
```

传给 `--manifest` 的输入是包含 start/end/speaker 的 `cut_segments.csv`，不是直接传给 C++ runner 的 TSV。

`transcript_empty` 是已完成的空转写状态，不等于执行崩溃。

### `board/board_meeting_chain_profile.py`

历史独立链路 CLI，但其中的 `MemorySampler` 和进程结束辅助函数仍被生产 Harness 导入，因此仍是板端运行依赖。不要把该脚本的独立 CLI 当作当前完整会议生产入口。

## 生产 Harness

仓库源码：

```text
meeting_harness/
```

板端部署：

```text
/userdata/meeting_agent/scripts/harness/
```

板端入口：

```bash
cd /userdata/meeting_agent/scripts

python3 -m harness.main \
  --source-audio /path/to/meeting.flac \
  --out-dir /userdata/meeting_agent/output/meeting_run \
  --overwrite
```

正式链路和产物见根目录 [README](../README.md)，上下文、章节、speaker batch、验证和发布机制见 [架构说明](../docs/architecture.md)。

## 板端诊断

### `board/rkllm_smoke_test.py`

检查 LLM 模型文件，启动 `rkllm3-server` 并执行基础 smoke。用于模型和服务诊断，不生成正式会议结果。

### `board/board_asr_direct_flac_eval.py`

直接把原始音频送入 ASR，用于观察长音频直接识别的完整度和限制。

### `board/board_asr_standard_wav_eval.py`

将标准化 mono WAV 切片后评估 ASR，用作长音频覆盖基线。

### `board/board_asr_eval_common.py`

上述 ASR 诊断脚本共享的命令、音频和结果处理 helper。

当前工作区可能存在未跟踪的 `board_harness_*` 或 chapter inspection 脚本。它们尚未进入正式提交面，因此不在本索引中列为支持入口。

## Diarization / TextGrid / ASR 分析

### `diarization/compare_diarization_textgrid.py`

对比 3D-Speaker RTTM 和 TextGrid speaker tier，计算时间重叠与匿名 speaker 映射结果。

### `diarization/diarization_missed_intervals.py`

统计 RTTM 未覆盖或覆盖不足的 TextGrid speech interval。

### `diarization/diarization_padding_scan.py`

扫描 RTTM padding，观察 speech recall、precision 和 speaker attribution 变化。

### `diarization/diarization_gap_fallback_plan.py`

分析 padding 后的未覆盖 gap，生成 `speaker=unknown` 兜底候选。

### `diarization/diarization_segment_plan_stats.py`

归并 known speaker 段、补 unknown、生成最终 ASR segment plan，并输出 TextGrid-relative 诊断指标。

### `diarization/cut_audio_by_segment_plan.py`

根据 segment plan 切出 WAV，并统计片段和存储信息。

### `diarization/evaluate_segment_asr_with_textgrid.py`

读取 segment ASR 结果，与 TextGrid 对齐计算 CER 和 speaker/coverage 诊断，并生成可读 Timeline 对比。

这些工具用于研究和评估，不替代 `meeting_harness.main` 的生产编排。

## Local only

`scripts/local_only/` 由 `.gitignore` 排除，用于保存：

- 一次性模型转换和量化实验；
- 已被 Harness 替代的 profile；
- RKLLM setup/context/memory probe；
- 外部 3D-Speaker 源码补丁；
- 非正式 RKNN diarization 实验；
- 早期 legacy pipeline。

该目录不是 GitHub 发布面。规范文档不要链接其中脚本作为可复现的正式入口。

## 板端路径差异

仓库中的脚本路径是：

```text
scripts/board/<name>.py
```

板端部署通常将脚本平铺为：

```text
/userdata/meeting_agent/scripts/<name>.py
```

Harness 的默认 `--board-scripts-dir` 指向板端平铺目录。新增或移动生产依赖时，必须同时检查 Harness 拼接的文件名和板端部署布局。
