# meet 评测框架

> 口径已对齐现实(2026-09-14):**核心 = 自建确定性评测(独立 Python,主判据)**;
> **DeepEval = 可选 CI 皮**(把 L1 指标包成 BaseMetric + GEval 裁判,为 CI 门禁);
> **裁判默认本地 Ollama(无 key、不出网)**,决策符合度权威用 opus 子agent,云千问可选。
> 主入口 `python eval/run_all.py` → `reports/RESULTS_main`。全景见 `评测框架总览.md`,契约见其 §四。

**注意主次**:本项目 62 个评测脚本里只有 6 个用 DeepEval;银标召回 / 维度 / 决策符合度 / 转写 / 分章
全是独立 Python,不依赖 DeepEval 也能全跑。DeepEval 只贡献 L2 的 GEval 裁判指标 + `deepeval test run` CI 壳。

下面这套 DeepEval 8 指标是**其中的 L1+L2 封装**(评测跑 PC/CI,不上板端;裁判可本地/云,不影响端侧离线部署):

## 指标(8 个,两层)+ 裁判校准

| 层 | 指标 | 实现 | 性质 |
|---|---|---|---|
| **L1 确定性** | 关键点召回 | `metrics/keypoint_recall_metric.py`(复用 `summary/keypoint_recall.py`) | 对人工金标,搜全层(章节+enrichment),**判定依据** |
| **L1 确定性** | 低频精确召回 | 同上(`low_freq_only`:anchor 含数字/中文数字子类) | 对标飞书/阿里最大短板 |
| **L1 确定性** | 锚点支持率 | `metrics/deterministic_metrics.py` | 证据可回溯率(refs 落到真实原文段)——项目卖点 |
| **L1 确定性** | 关键词纯净度 | 同上 | 议题词占比(不含人名/部门),量化 P1 去噪 |
| **L1 确定性** | 决策owner归属率 | 同上 | 带负责人的决策占比,对标飞书说话人归属 |
| **L2 裁判** | 忠实度 | `metrics/geval_metrics.py` G-Eval,千问 | 不编造,数字/专名对得上 |
| **L2 裁判** | 完整度 | 同上 | 覆盖主要议题/关键结论 |
| **L2 裁判** | 简洁相关度 | 同上 | 精确侧:简洁/不跑题/无冗余 |

**裁判校准** `judge/calibrate.py`:用人工金标当真值,逐关键点问裁判"覆盖没有",与确定性召回比一致率。
≥0.8 → 裁判的完整度判断可采信(实测 g1/g2 = 0.818,达标)。

> 注:DeepEval `SummarizationMetric`(摘要专用,精确+覆盖)配 qwen3.8-max(慢)+全文会超时,
> 未入默认套件;精确侧改用轻量 G-Eval 简洁相关度。需要时换更快裁判(qwen-plus)再启用 Summarization。
> 分章 Pk/WindowDiff 需人工金标边界(g1/g2 暂无),`topic_segmentation/pk_windowdiff.py` 备用,有金标再接。

## 组成

```
eval/
├── judge/qwen_judge.py       # 千问接入 DeepEval(DashScope OpenAI 兼容端点)
├── metrics/                  # 指标(DeepEval BaseMetric)
│   ├── keypoint_recall_metric.py
│   └── geval_metrics.py
├── deepeval_suite.py         # 整合套件:板端产物+金标 → 4指标 → 报告
├── eval_config_deepeval.json # 会议清单(meeting_result + golden)
├── golden/*.keypoints.json   # 人工关键点金标
├── summary/keypoint_recall.py# 召回底层逻辑(被 metric 复用)
└── reports/                  # 产出 RESULTS_deepeval.md / .json
```

## 运行

```powershell
$env:DASHSCOPE_API_KEY="sk-..."      # 千问 key,只走环境变量,不写进代码/仓库
$env:PYTHONIOENCODING="utf-8"
$env:DEEPEVAL_TELEMETRY_OPT_OUT="YES"
$env:DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE="900"   # 全文喂裁判,给足超时
python eval\deepeval_suite.py --config eval\eval_config_deepeval.json --out eval\reports\deepeval
```

## 注意

- **API key 只从 `DASHSCOPE_API_KEY` 环境变量读**,不硬编码、不提交。
- 忠实/完整度**必须喂全文原文**给裁判(截断会让裁判误判"编造",伤效度)。
- 输入为板端产物;改造后需**重跑板端**再评(003 是旧版 enrichment)。
- 依赖:`pip install deepeval openai`(仅开发机,不上板)。
