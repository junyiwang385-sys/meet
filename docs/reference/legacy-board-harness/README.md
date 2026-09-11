# RK1828 离线会议 Agent

本项目实现并评估一条部署在 RK1828 上的离线会议处理链路：从真实会议音频生成带匿名发言人和时间信息的转写，再由本地 Qwen 模型生成可追溯、可校验的结构化会议总结。

```text
会议音频
-> SoX 标准化
-> 3D-Speaker diarization
-> speaker/unknown segment plan
-> Qwen3-ASR Batch 转写
-> canonical transcript / Timeline
-> Qwen3-4B ctx16k
-> Python 校验与确定性归并
-> 会议总结、展示数据和兼容导出
```

项目重点是板端生产 Harness、质量验证和结果发布，不包含前端应用实现。当前生产模型为 Qwen3-4B ctx16k；运行时保留 Qwen3 thinking，并将 thinking 与最终 JSON 分开保存。主线总结固定采用 `sliding_chapter_windows`，不再使用一次性全量总结。

## 生产入口

仓库中的 Python 包名是 `meeting_harness`。部署到板端后，包通常位于 `/userdata/meeting_agent/scripts/harness/`，因此板端模块名是 `harness.main`。

板端最小运行示例：

```bash
cd /userdata/meeting_agent/scripts

python3 -m harness.main \
  --source-audio /path/to/meeting.flac \
  --out-dir /userdata/meeting_agent/output/meeting_run \
  --overwrite
```

- `--overwrite`：清理并重建非空输出目录；
- `--resume`：校验输入、配置和产物身份后复用已完成阶段；
- 两者互斥。已有非空输出目录且未指定其中之一时，Harness 会拒绝运行。

完整参数以以下命令和 [meeting_harness/main.py](meeting_harness/main.py) 为准：

```bash
python3 -m harness.main --help
```

如果直接从仓库源码目录启动，模块名使用 `meeting_harness.main`，并根据实际部署位置覆盖板端脚本、3D-Speaker、ASR 和模型目录。

## 运行前提

仓库不包含模型权重、数据集、RKNN3 Runtime、3D-Speaker 上游仓库或完整 Python 环境锁文件。生产运行需要预先准备：

- RK1828 与已验证的 RKNN3 Runtime；
- `sox`；
- CPU/Torch 版 3D-Speaker 及其 Python 环境；
- Qwen3-ASR Batch runner、`lib/` 和六类模型文件；
- `/usr/bin/rkllm3-server`；
- Qwen3-4B ctx16k 的 `.rknn`、`.weight`、`.tokenizer.gguf`、`.embed.bin`；
- 可写的输出目录。

生产默认路径和参数集中在 [meeting_harness/main.py](meeting_harness/main.py)，不要依赖历史文档中的旧模型目录或机器地址。

## 当前上下文配置

| 参数 | 当前默认值 |
| --- | ---: |
| `ctx` | `16384` |
| `predict` | `4096` |
| `max_tokens` | `4096` |
| 输入安全余量 | `512` |
| 启发式输入预算 | `11776` |
| 字符/token 估算 | `1.3` |
| 固定估算开销 | `128` |

`11776 = 16384 - 4096 - 512`。当前默认预留 4096 tokens 给 Qwen3 thinking 和最终 JSON；固定开销用于 Prompt token 启发式估算，不会再次从上下文窗口中扣除。当前实现不是严格 tokenizer 计数。

当前主线统一使用 `sliding_chapter_windows`，不再根据输入长度选择一次性全量请求。处理顺序为：

1. 按 canonical Timeline 构造章节窗口；
2. 通过 `carryover_start_ref` 推进未完成话题；
3. 汇总已校验章节生成全文摘要；
4. 对待办候选执行 action review；
5. 通过独立 speaker batches 生成发言人总结。

一次性全量总结仅作为历史实现保留，不属于当前运行路径。固定滑动窗口主线已在 30 个样本上完成板端验证，其中包括前 10 组和后 20 组复用既有 ASR 结果的运行；当前默认输出预算已统一为 4096，后续质量评测仍应以 4K 配置为准。

详细机制见 [架构说明](docs/architecture.md)。

## 输出与权威性

一次运行的主要目录如下：

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

关键产物：

- `meeting_result.json`：整次运行状态、阶段耗时、错误、内存和产物清单；失败时也会尽量写出；
- `03_llm_summary/canonical_segments.json`：精确毫秒时间、匿名 speaker、ASR 文本和稳定 segment ID；
- `meeting_summary.json`：最终校验通过后发布的 evidence-linked 内部总结；
- `03_llm_summary/validation.json`：schema、refs、边界修复和发布校验证据；
- `meeting_frontend.json`、`meeting_display.txt`：从 canonical transcript 和权威总结确定性生成的展示结果；
- `04_compat_export/`：兼容外部格式的派生结果，不是内部事实源；
- `runtime/memory_summary.json`：板端内存采样汇总。

只有 `meeting_result.json` 为 `status: "ok"`、最终 validation 通过，并且 summary、frontend、display 与兼容导出来自同一次成功发布，才能认定完整 Harness 成功。单次 HTTP 响应成功或 `context_truncated=false` 不等于最终会议结果已发布。

## 评测

软件测试与模型质量评测分开：

```bash
# 软件回归测试
python -m pytest tests

# 已有 canonical Timeline 的摘要评测
python -m evals.run_eval --vcsum-root /path/to/vcsum

# 真实音频端到端评测
python -m evals.run_e2e_eval \
  --manifest /path/to/e2e_manifest.json \
  --pipeline-output-root /path/to/pipeline_outputs

# 从官方 TextGrid 准备 E2E expected 与 manifest
python -m evals.prepare_e2e_expected \
  --dataset-root /path/to/dataset
```

真实音频 E2E 使用官方 TextGrid 或 canonical reference Timeline 作为事实真值，分别评估 diarization、ASR、speaker attribution、最终总结和运行时。Generated Timeline 是模型输出，不会替代参考事实源。CER 作为 TextGrid-relative ASR 诊断指标报告，不单独决定产品是否达标。

Judge 凭据通过环境变量提供，禁止写入源码或提交到 Git：

```bash
export ANTHROPIC_API_KEY="<key>"
export ANTHROPIC_BASE_URL="<messages-api-base-url>"  # 可选
```

完整说明见 [评测指南](evals/README.md)。

## 代码结构

```text
meeting_harness/    生产编排、canonical transcript、LLM、校验和发布
scripts/board/      Harness 直接依赖与板端诊断脚本
scripts/diarization/diarization、TextGrid 和 segment/ASR 分析工具
evals/              Timeline 与真实音频 E2E 质量评测
tests/              软件回归测试
prompts/            Prompt 协议的可读版本
docs/               当前架构与历史工程记录
```

本地模型、数据、生成结果、上游仓库和一次性实验目录不属于正常提交面。

## 文档

- [当前架构](docs/architecture.md)
- [评测指南](evals/README.md)
- [脚本索引](scripts/README.md)
- [RK1828 / RKNN3 部署历史](docs/rk1828_qwen_asr_llm_deployment_summary.md)
- [问题、实验与解决方案历史](docs/rk1828_meeting_agent_issues_and_solutions.md)
- [Legacy 综合记录](docs/history/mainDoc.md)

当前行为以代码、测试和具体运行产物为准；历史文档中的路径、模型和结论可能已被后续实现替代。

## 已知限制

- 输入 token 数仍采用字符比例启发式估算；
- 单个 speaker 文档超预算时保留按时间排序的最长前缀，尚未实现 speaker chunk/merge；
- 匿名 speaker 不映射真实姓名；
- ASR 的否定、数字、术语和责任对象错误可能继续传递到摘要，必须结合 refs 和参考评测检查；
- 仓库没有提交模型、真实评测数据集、CI 配置或固定依赖锁文件。
