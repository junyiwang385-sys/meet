# 板端脚本快照清单

> 本地路径：`D:\Meeting_Agent_fresh\board_sync_20260820\scripts`  
> 板端来源：`/userdata/meeting_agent/scripts`  
> 同步日期：2026-08-20  
> 定位：板端部署代码快照，不是独立可运行包，也不是当前仓库源码的自动镜像。

## 一、实际运行链路

```text
board_agent_api_v0.py
  → board_harness_worker_v0.py
  → harness/main.py
  → harness/pipeline.py
    → board_3dspeaker_segment_prepare_absorb_unknown.py
    → board_segment_asr_batch.py
    → harness/transcript.py
    → harness/product_summary.py
    → harness/validation.py
    → harness/compat_export.py
    → harness/display.py
```

`harness/llm.py` 通过 `importlib.util` 动态加载 `board_meeting_chain_profile.py`，当前使用其中的 `MemorySampler` 和 `terminate_process`。因此该 `profile` 文件属于正式运行依赖，不能仅根据文件名归为测试脚本。

## 二、最小正式 Python 运行文件

### 服务和阶段入口

```text
board_agent_api_v0.py
board_harness_worker_v0.py
board_meeting_chain_profile.py
board_3dspeaker_segment_prepare_absorb_unknown.py
board_segment_asr_batch.py
```

### Harness 包

```text
harness/__init__.py
harness/main.py
harness/pipeline.py
harness/artifacts.py
harness/chunking.py
harness/transcript.py
harness/llm.py
harness/product_summary.py
harness/validation.py
harness/compat_export.py
harness/display.py
```

最小代码集合共 16 个 Python 文件。这里只表示 Python 源码依赖，不包含模型、原生可执行文件和系统环境。

## 三、其他快照文件分类

| 类别 | 文件示例 | 当前定位 |
|---|---|---|
| 旧分段/串联实现 | `board_3dspeaker_segment_prepare.py`、`board_3dspeaker_asr_chain.py` | 历史或回滚参考，不在当前 Harness 主链路 |
| ASR 评估 | `board_asr_eval_common.py`、`board_asr_direct_flac_eval.py`、`board_asr_standard_wav_eval.py` | 评测工具 |
| 性能和统计 | `board_full_meeting_pipeline_profile.py`、`board_timeline_summary_profile.py`、`board_harness_*_stats.py` | 分析工具 |
| smoke/probe | `rk1828_v104_meeting_chain_smoke.py`、`board_rkllm_*_probe.py`、`board_harness_timeline_test.py` | 验证工具 |
| 纪要旧实验 | `board/minutes/meeting_*_map_reduce_v0.py` | 旧纪要基线，与当前 `product_summary.py` 并存 |
| 一次性 patch | `patch_*.py` | 板端历史修补记录，不自动执行 |
| 历史备份 | `*.bak_*`、`*.previous`、`*.v11`、`*.pre_harness_*` | 保留用于追溯 |
| 运行缓存 | `__pycache__/*.pyc` | 可再生缓存；快照中保留但不计入 SHA-256 清单 |

## 四、外部运行依赖

### 说话人分段

```text
/userdata/3D-Speaker
/userdata/miniforge3/envs/3dspeaker/bin/python
/userdata/3D-Speaker/speakerlab/bin/infer_diarization.py
sox
```

### Qwen3-ASR Batch

```text
/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo
/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn
```

模型目录至少包含：

```text
encoder.rknn
encoder.weight
llm.rknn
llm.weight
llm.tokenizer.gguf
llm.embed.bin
```

### Qwen3-4B 16K

```text
/usr/bin/rkllm3-server
/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k
```

LLM 模型目录需要各一份：

```text
*.rknn
*.weight
*.tokenizer.gguf
*.embed.bin
```

此外仍依赖板端 RKNN/RKLLM 动态库、SoX、Torch/3D-Speaker Python 包、权限、环境变量和服务启动方式。这些均未包含在当前快照中。

## 五、服务能力边界

当前 Board Agent：

- 协议：`board-agent.v1`
- Agent 版本：`0.2.0`
- 模型配置：`qwen3-4b-v104-ctx16k`
- 只在内存保存一个任务；服务重启后不能恢复任务状态
- 只允许一个活动任务
- 支持任务创建、音频上传、状态查询、取消和结果读取
- 尚未包含正式鉴权、TLS、持久化队列和板端录音 API

## 六、完整性与校验

该目录可以用于代码分析和板端部署版本追溯，但不能单独重建 RK1828 运行环境。46 个非 `.pyc` 文件的 SHA-256 位于：

```text
manifests/board-sync-20260820.sha256
```

整理项目目录时没有改名、移动或清理此快照。
