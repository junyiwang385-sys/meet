# Meeting Agent 质量评测

`evals/` 用于模型和完整生产链路的质量评测；`tests/` 用于 Python 软件回归测试，两者不能混为一类结果。

当前生产总结主线固定使用 `sliding_chapter_windows`，不再使用一次性全量总结；本地 Qwen 默认使用 `ctx=16384`、`predict/max_tokens=4096` 和 512-token 输入安全余量。固定滑动窗口主线已在 30 个样本上完成板端验证，其中包含前 10 组和后 20 组复用既有 ASR 结果的运行；后续质量评测统一以 4K 配置为准，ASR、canonical Timeline 和上游时间段处理不属于本次 Prompt 评测的变更范围。

当前支持两种评测：

| 模式 | 入口 | 输入起点 | 主要用途 |
| --- | --- | --- | --- |
| Timeline / VCSum | `python -m evals.run_eval` | 已有 canonical Timeline | 单独评估本地摘要和 Judge |
| 真实音频 E2E | `python -m evals.run_e2e_eval` | 真实音频 | 评估 diarization、ASR、摘要、运行时和 Judge |

评测协议的四个主要业务字段是：

```text
overview
chapters
speakers
action_items
```

旧数据中的 `speaker_key_points`、`key_points`、`decisions`、`open_questions`、`risks`、`keywords` 可作为辅助信息，但不作为当前四字段产品协议的核心 gold。

## Judge 凭据

Judge 通过现有的 Anthropic-compatible Messages HTTP 接口调用，不需要修改 Python 源码。凭据从环境变量读取：

```bash
export ANTHROPIC_API_KEY="<key>"
export ANTHROPIC_BASE_URL="<messages-api-base-url>"  # 可选
```

不要把真实 key 写入 `evals/llm_judge.py`、命令历史、评测结果或 Git。

不需要远程 Judge 时使用 `--skip-judge`。当前默认模型：

- Timeline/VCSum Judge：`claude-opus-5`；
- 真实音频 E2E Judge：`claude-fable-5`；
- E2E expected 准备：`claude-opus-5`。

具体值以各入口的 `--help` 为准。

## Timeline / VCSum 评测

`run_eval.py` 从 canonical Timeline 开始，调用本地 Qwen 摘要流程，再执行 deterministic grader 和远程 Judge。

数据目录需要包含 `vcsum_manifest.json`、Timeline 和 expected JSON。示例：

```bash
python -m evals.run_eval \
  --vcsum-root /path/to/vcsum \
  --output-root /path/to/eval-output \
  --cases vcsum_technical_02_id48
```

无 API smoke：

```bash
python -m evals.run_eval \
  --vcsum-root /path/to/vcsum \
  --output-root /path/to/eval-output \
  --limit 1 \
  --skip-judge
```

已有候选总结时，可以用 `--candidate-summary` 或 `--candidate-summary-root` 跳过本地模型；`--resume-candidate` 用于复用已生成候选。完整参数见：

```bash
python -m evals.run_eval --help
```

## 真实音频 E2E

E2E 评测执行正式生产链：

```text
真实音频
-> diarization
-> Batch ASR
-> Generated Timeline
-> 本地 Qwen summary
-> Timeline/deterministic metrics
-> remote Claude Judge
```

### 真值边界

- 官方 TextGrid 或预构造的 canonical reference Timeline 是事实真值；
- Generated Timeline 是待评模型输出，不能替代参考事实源；
- Generated Timeline 只用于评估上游质量，以及解释 candidate summary 中的生成侧 refs；
- Judge 的 Faithfulness 必须回到 reference Timeline 核对；
- expected JSON 中的 `core_facts` 用于核心内容覆盖率；如果 expected 是从 TextGrid 经 LLM 整理得到，必须标记为 LLM-assisted，不得称为独立人工 gold。

### Manifest

每个 case 至少需要：

- `audio_file`：生产 Harness 接受的真实音频；
- `reference_timeline_file`：官方 `.TextGrid` 或 canonical Timeline 文本；
- `expected_file`：包含四个主要业务字段以及 `core_facts` 的 expected JSON。

路径相对于 manifest 所在目录解析，也可以通过 `--dataset-root` 指定根目录。case 可选提供 `pipeline_output_dir` 复用指定 Harness 结果。

示例见 [e2e_manifest_example.json](e2e_manifest_example.json)。

### 从 TextGrid 准备 expected

当数据集有官方 TextGrid 转写但没有会议级摘要标签时：

```bash
python -m evals.prepare_e2e_expected \
  --dataset-root /path/to/dataset
```

默认发现：

```text
<dataset-root>/test/wav + TextGrid
<dataset-root>/train_L/wav + TextGrid
<dataset-root>/train_S/wav + TextGrid
```

默认输出：

```text
<dataset-root>/e2e_expected/<split>/<case>_expected.json
<dataset-root>/e2e_expected/_metadata/<split>/<case>.json
<dataset-root>/e2e_expected/preparation_manifest.json
<dataset-root>/e2e_manifest.json
```

`--resume` 会校验并复用符合当前 schema 的标签；缺少 `core_facts` 的旧标签需要重新生成。首次运行建议使用 `--limit 1`；也可用 `--cases` 选择 case。

这些 expected 是由官方 TextGrid 整理出的 LLM-assisted labels。`core_facts` 只保留一场会议应被摘要覆盖的主要议题、重要结论、明确行动、风险和关键限制；原始 TextGrid 仍是 CER、时间覆盖、speaker attribution 和 Faithfulness 的事实源。

### 运行 E2E

板端部署布局：

```bash
python -m evals.run_e2e_eval \
  --manifest /path/to/e2e_manifest.json \
  --pipeline-output-root /path/to/pipeline-output \
  --output-root /path/to/eval-output
```

默认 `--harness-module harness.main` 对应板端部署包。从仓库源码包启动时改为：

```bash
python -m evals.run_e2e_eval \
  --manifest /path/to/e2e_manifest.json \
  --harness-module meeting_harness.main \
  --board-scripts-dir /path/to/repo/scripts/board \
  --pipeline-output-root /path/to/pipeline-output \
  --output-root /path/to/eval-output
```

源码模式仍需要实际 3D-Speaker、ASR、RKNN Runtime 和模型路径，不能在普通开发机上凭空运行硬件链路。

无 Judge smoke：

```bash
python -m evals.run_e2e_eval \
  --manifest /path/to/e2e_manifest.json \
  --pipeline-output-root /path/to/pipeline-output \
  --limit 1 \
  --skip-judge
```

### 复用与重试

- `--pipeline-output-root ROOT`：Harness 产物位于 `ROOT/<case_id>`；
- `--reuse-pipeline`：直接读取已完成产物，不重跑音频、diarization、ASR 或本地 Qwen；
- `--resume-pipeline`：让 Harness 校验并复用已完成阶段，继续中断运行；
- `--reuse-judge-run-dir OLD_RUN`：读取 `OLD_RUN/<case_id>/judge_response_raw.json` 并离线重新归一化，不重新调用 Judge；
- `--skip-judge`：只执行 pipeline 与 deterministic metrics。

`--reuse-pipeline` 适合 Judge 重试和离线重建报告；`--resume-pipeline` 适合生产 Harness 尚未完成的 case。`--skip-judge` 与 `--reuse-judge-run-dir` 互斥。

## 指标

### Timeline / ASR / speaker

- corpus CER 与 macro CER；
- speech recall 与 speech precision；
- reference/predicted speech duration；
- anonymous speaker 最优一对一映射后的 attribution accuracy；
- predicted/reference speaker count 与 count error；
- unknown segment/time ratio；
- segment count、空文本和时长差诊断。

CER 定义为：

```text
(substitution + deletion + insertion) / reference character count
```

CER 是相对于 TextGrid 文本的诊断指标。若 TextGrid 不是逐字转写，CER 不应被单独解释为最终产品达标线。

### Summary

Faithfulness：

```text
(supported + 0.5 * partially_supported) / all verifiable claims
```

核心内容覆盖率（Core Content Coverage）：

```text
Σ(核心事实权重 × 覆盖系数) / Σ核心事实权重
```

其中：

```text
covered = 1
partial = 0.5
missing = 0

critical = 3
major = 2
```

核心内容覆盖率只使用 expected 中显式、去重的 `core_facts` 作为分母。Candidate 的 overview、chapters、speakers 或 action_items 任一部分覆盖该事实都可以计分，同一事实只计算一次。`core_facts` 的数量按会议复杂度和独立核心事实的实际数量确定，不设固定条数，单场技术上限为 30 条；每条事实必须有 Reference Timeline refs 支持。由官方 TextGrid 经 LLM 整理的 expected 必须标记为 LLM-assisted labels，不能称为独立人工 gold。旧版由总览、章节和行动项共同构成的 `weighted_completeness` 仅作为 legacy 结果保留，不与新指标混合。

Faithfulness 关注“摘要写出的事实是否有依据”，核心内容覆盖率关注“会议中的重要内容是否被摘要覆盖”。

同时报告：

- pipeline completion；
- Judge success；
- critical errors；
- schema/ref/章节连续性/speaker attribution/action-item deterministic checks；
- structure 和 readability 诊断。

### Runtime

- 端到端总耗时；
- segmentation、Batch ASR、transcript、LLM summary、compat export 阶段耗时；
- 本地 Qwen 实际 request time；
- 板端内存峰值；
- failure stage/code 分布。

## E2E 输出

```text
<output-root>/<run-id>/
├── run_manifest.json
├── aggregate.json
├── report.md
└── <case-id>/
    ├── case_metadata.json
    ├── reference_timeline.txt
    ├── expected.json
    ├── pipeline_command.json
    ├── pipeline.log
    ├── pipeline_record.json
    ├── generated_timeline.txt
    ├── timeline_metrics.json
    ├── candidate_summary.json
    ├── deterministic_grade.json
    ├── judge_request.json
    ├── judge_response_raw.json
    └── judge_result.json
```

`aggregate.json` 是机器聚合结果，`report.md` 是可读报告。报告需要同时展示完成率和 Judge 成功率，避免把部分失败 run 表述为完整结果。

## 辅助工具

- `finalize_retry_run.py`：整理重试后的 run；
- `merge_eval_runs.py`：合并多次评测结果；
- `reprocess_run.py`：离线重新处理已保存结果；
- `reports/build_report.py`：生成或重建报告；
- `textgrid.py`：官方 TextGrid 解析；
- `e2e_metrics.py`：Timeline、CER、时间覆盖和 speaker metrics。

运行任何批量评测前，先用 `--limit 1` 做真实 case smoke，并检查参考 Timeline、candidate summary、Judge raw response 和 aggregate 是否属于同一 case。
