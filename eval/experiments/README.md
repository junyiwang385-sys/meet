# 一次性实验归档（experiments/）

> 这里是**已得出结论、不再常跑**的探索性实验脚本。与之相对，`eval/` 主目录只保留**正式指标脚本**
> （常跑、可回归、进报告）。归档=保留可复现脚本，但结论已固化进文档，接手人**先读结论、不必重跑**。
> 分类依据见 `eval/评测框架总览.md`。2026-09-14 归档。

## 正式指标（留在主目录，未归档，供对照）

- `golden_v2/score_candidate.py`（核心事实召回，主判据）、`score_dimensions.py`（维度质量，`--clean` n=30）
- `golden_v2/` 银标流水线：`build_timeline / gen_prompt / validate_golden / verify_golden / render_review / normalize / timeline_to_result`
- `transcription/run_point{1,2,3,4}_*.py` + `score_asr / score_board_diar / normalize / run_vad_sweep`
- `topic_segmentation/pk_windowdiff / cohesion_boundary_recall / run_seg_v2_blocks / run_seg_v2_multi`
- `summary/keypoint_recall.py`、`metrics/*`、`judge/*`、`deepeval_suite.py`、`run_deepeval_clean.py`、`judge_conformance.py`、`pc_full_minutes.py`、`run_eval.py`

---

## 归档实验清单（脚本 · 测什么 · 结论 · 结果位置）

### 摘要设计取舍（4B 能力边界验证）→ `experiments/`

| 脚本 | 测什么 | 结论 | 报告 |
|---|---|---|---|
| `chunk_size_experiment.py` | 每次喂 k 章，召回随输入长度 | 找到"喂到几章崩"拐点（印证 7k 断崖） | `reports/chunk_size_g2/RESULTS_chunk_size.md` |
| `context_experiment.py` | A0 隔离 vs A1/A2 带上下文 | 带上下文 recall 微升但串味(contam/bleed)↑ → **A0 隔离更优**（CLAUDE 原则4） | `reports/ctx_exp_g1*/RESULTS.md` |
| `bilateral_context_experiment.py` | A3b 前后章参考 vs A0 | 双边上下文串味更高 | `reports/a3b_g2/RESULTS_a3b.md` |
| `a0_vs_a1_production.py` | 生产级细粒度 A0 vs A1 | A0 召回更高、串味更低 | `reports/a0_vs_a1/` |
| `batch_summary_experiment.py` | 一次喂 b 段，结构完整率/召回 | b↑→结构完整率↓召回↓，"批量到几段崩" | `reports/batch_g2/RESULTS_batch.md` |
| `cross_ref_check.py` | 章头指代是否断裂 | 跨指代诊断 | `reports/cross_ref/` |

### 摘要召回/打捞/去噪 → `golden_v2/experiments/`

| 脚本 | 测什么 | 结论 |
|---|---|---|
| `pc_a0_recall.py` · `pc_recall_detail.py` | 同输入仅换 A0 的召回增益 | 召回 **0.429→0.643** |
| `pc_denoise_experiment.py` | must_cover 补召回（去噪配对） | **反伤 −5pp，弃回退**（碰生成的补召回都伤 4B） |
| `pc_salvage_recall.py` · `pc_salvage2_recall.py` · `pc_exhaustive_recall.py` · `salvage_filter_study.py` | 确定性补低频数字 | 纯后处理 `keyword_index` 有效 |
| `pc_keyword_accuracy.py` · `pc_keyword_improved_test.py` · `pc_keyword_test5.py` | 关键词准确率 + 纯净度 | 通用构词规则跨域通杀、议题词零误伤 |
| `pc_hotword_ab.py` | ASR 热词偏置 A/B | **B-WER 0.186→0.083、echo=0**（PC 验证 GO） |
| `pc_integrated_rerun.py` | 改过的 product_summary 集成复跑 | 一次性回归 |

### 转写一次性验证 → `transcription/experiments/`

| 脚本 | 测什么 | 结论 |
|---|---|---|
| `run_p1_full30.py` | 全 30 场 VAD thres 0.6 vs 0.2 泛化 | 整句丢 28%→9%，全场泛化 |
| `run_p1_remeasure.py` | 点1 改后重测（g1/g2/g5） | — |
| `run_p4_board_ba.py` | 点4 板端 before/after | — |
| `board_vad_verify.py` · `_diag_sent_align.py` | 板端真 rttm VAD 验证 + 句对齐诊断 | — |

### 分章实验 → `topic_segmentation/experiments/`

| 脚本 | 测什么 | 结论 |
|---|---|---|
| `discourse_segmenter.py` | 话语标记(discourse cue)边界补测 | 单场 Pk→0.190（cue 跨会泛化未验） |

---

> 注：`eval/finetune/`（QLoRA 微调，负结果召回 0.167→0.024）本身是自成一体的封闭实验目录，未并入此处；
> 其结论见 `docs/实验与各阶段成果.md` 阶段十二。
