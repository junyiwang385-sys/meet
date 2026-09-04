# 评测结果（多场会）

会议数: 5  |  评测框架: eval/run_eval.py（可复现）

## 汇总（均值 ± 标准差）

| 指标 | 均值 | 标准差 | 场次 | 说明 |
|---|---|---|---|---|

## 逐场·结果质量（对金标准）

| 会议 | 关键点召回 | Pk | WindowDiff | 纠回率 | 精确率 | CER |
|---|---|---|---|---|---|---|
| g1 | - | - | - | - | - | - |
| g2 | - | - | - | - | - | - |
| g3 | - | - | - | - | - | - |
| g4 | - | - | - | - | - | - |
| g5 | - | - | - | - | - | - |

## 逐场·过程/系统指标（来自结构化日志 run_report）

| 会议 | 块数→章数 | 块摘要均字 | 重试 | prompt tokens | 总耗时(s) |
|---|---|---|---|---|---|
| g1 | 9→9 | 98.1 | 0 | 61724 | 513.623 |
| g2 | 8→8 | 85 | 1 | 61096 | 474.316 |
| g3 | 9→9 | 90.6 | 0 | 66610 | 503.655 |
| g4 | 8→8 | 97.6 | 0 | 67972 | 580.674 |
| g5 | 8→8 | 90.2 | 0 | 56719 | 525.234 |

## 逐场·内容丰富 + 性能（全部来自结构化日志，自动汇总，无手填）

| 会议 | 时长(s) | run状态 | enrich stage | enrichment(kw/qa/quote/dec/outline) | 金句保真 | 总耗时(s) | 摘要(s) | enrich(s) | 只加载一次 | server就绪(s) | 板端峰值(MB) | RSS峰值(MB) | 疑似泄漏 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| g1 | 1862.3 | succeeded | succeeded | 18/45/3/30/Y | 3 | 513.623 | 142.806 | 119.951 | True | 15.028 | 2738.914 | None | None |
| g2 | 1990.2 | succeeded | succeeded | 18/15/3/18/Y | 3 | 474.316 | 138.673 | 94.361 | True | 15.028 | 2652.688 | None | None |
| g3 | 2127.0 | succeeded | succeeded | 18/45/3/27/Y | 3 | 503.655 | 152.389 | 118.393 | True | 15.026 | 2643.07 | None | None |
| g4 | 2040.4 | succeeded | succeeded | 18/36/3/17/Y | 3 | 580.674 | 137.683 | 126.445 | True | 16.032 | 2702.477 | None | None |
| g5 | 1862.0 | succeeded | succeeded | 18/17/3/22/Y | 3 | 525.234 | 140.529 | 94.463 | True | 16.027 | 2710.133 | None | None |

## 自动优化红旗（来自 run_report）

**g1**：
- 🚩 块摘要偏短：均 98.1 字 < 目标 120
- 🚩 overview 偏短：245 字 < 目标 300
- 🚩 overview 走了有损章节归并（未接地原文）
- 🚩 合并率低：9 块仅并到 9 章（continues_previous 合并偏保守）
- 🚩 chars_per_token 需校准：实测 1.525 vs 配置 1.3（预算估算偏差）
- 🚩 空 schema 字段：key_points, decisions, open_questions, risks, keywords（未抽取）

**g2**：
- 🚩 块摘要偏短：均 85 字 < 目标 120
- 🚩 overview 偏短：216 字 < 目标 300
- 🚩 合并率低：8 块仅并到 8 章（continues_previous 合并偏保守）
- 🚩 chars_per_token 需校准：实测 1.637 vs 配置 1.3（预算估算偏差）
- 🚩 空 schema 字段：key_points, decisions, open_questions, risks, keywords（未抽取）

**g3**：
- 🚩 块摘要偏短：均 90.6 字 < 目标 120
- 🚩 overview 偏短：222 字 < 目标 300
- 🚩 合并率低：9 块仅并到 9 章（continues_previous 合并偏保守）
- 🚩 chars_per_token 需校准：实测 1.534 vs 配置 1.3（预算估算偏差）
- 🚩 空 schema 字段：key_points, decisions, open_questions, risks, keywords（未抽取）

**g4**：
- 🚩 块摘要偏短：均 97.6 字 < 目标 120
- 🚩 overview 偏短：137 字 < 目标 300
- 🚩 overview 走了有损章节归并（未接地原文）
- 🚩 合并率低：8 块仅并到 8 章（continues_previous 合并偏保守）
- 🚩 chars_per_token 需校准：实测 1.593 vs 配置 1.3（预算估算偏差）
- 🚩 空 schema 字段：key_points, decisions, open_questions, risks, keywords（未抽取）

**g5**：
- 🚩 块摘要偏短：均 90.2 字 < 目标 120
- 🚩 overview 偏短：275 字 < 目标 300
- 🚩 合并率低：8 块仅并到 8 章（continues_previous 合并偏保守）
- 🚩 chars_per_token 需校准：实测 1.627 vs 配置 1.3（预算估算偏差）
- 🚩 空 schema 字段：key_points, decisions, open_questions, risks, keywords（未抽取）

## 诚实边界
- 全部 PC 等价替代（Ollama GGUF Q4 / transformers Qwen3-ASR / modelscope diar），非板端 RKLLM/RKNN/板端 3D-Speaker 复现。
- 场次有限，非大规模 benchmark；金标准为人工标注。
- **关键未验：1-2h 长会（项目卖点）+ 板端端到端。**
- 摘要若用 LLM-judge，须注明用了哪个（更大/云端）模型，仅评测用、不属端侧部署。