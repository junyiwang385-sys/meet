# meet 评测框架

基于 **DeepEval**(业界开源 LLM 评测框架)+ **千问 qwen3.8-max 裁判**,融合项目已有的人工金标与召回逻辑。
评测跑在 PC/CI,不上板端;裁判用云端千问(比端侧 4B 大 → 判定可靠),不影响端侧离线部署。

## 指标(两层)

| 层 | 指标 | 实现 | 性质 |
|---|---|---|---|
| **L1 确定性** | 关键点召回 | `metrics/keypoint_recall_metric.py`(复用 `summary/keypoint_recall.py`) | 对人工金标,可复现,**判定依据** |
| **L1 确定性** | 低频精确召回 | 同上(`low_freq_only`:anchor 含数字/中文数字的子类) | 对标飞书/阿里最大短板 |
| **L2 裁判** | 忠实度 | `metrics/geval_metrics.py` G-Eval,千问裁判 | 不编造,数字/专名对得上;**参考** |
| **L2 裁判** | 完整度 | 同上 | 覆盖主要议题/关键结论;**参考** |

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
