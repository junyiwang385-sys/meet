# DeepEval 质量评测 · 干净输入线 n=30（复用 deepeval_suite 指标类）

> `eval/run_deepeval_clean.py`。输入=干净 timeline 真值转写跑出的 pipeline 产物（`eval/_pc_clean/<mid>`，
> meeting_summary + enrichment 拼成 meeting_result 形状）。2026-09-14。
> L1 确定性（无需 key，全 30 场）；L2 千问 G-Eval 忠实度/完整度/简洁度需 `DASHSCOPE_API_KEY`（未设→未跑）。

## L1 确定性（n=30）

| 指标 | 均值 | 解读 |
|---|---:|---|
| **AnchorSupport**（chapter/quote refs 是否锚到真实段） | **1.000** | 无悬空/编造锚点——**忠实度地板确认**（refs 校验强制保证） |
| **KeywordPurity**（关键词纯净率） | **1.000** | 关键词干净，无噪声/长句污染 |
| **DecisionOwner**（决策带负责人占比） | **0.138** | ⚠️ **只 14% 决策标了 owner**（阈值 0.3 未过）——真短板：4B 保守、不敢定归属，非编造（接地 1.0） |

## L1 关键点召回（人工金标，仅 4 场有 `eval/golden/*.keypoints.json`）

| | 值 |
|---|---:|
| 关键点召回（全部，n=4） | **0.979** |
| 关键点召回（低频，n=3） | **0.889** |

> ⚠️ **金标粒度不同，勿与 golden_v2 银标混比**：人工关键点更粗（高层要点）→ 召回 0.98；
> golden_v2 银标更细（含大量低频数字）→ core 召回 0.82、低频 0.69（见 `golden_v2/RESULTS_dimensions.md`）。
> 两者都真，是"金标严不严"的差别，不是矛盾。

## L2 千问 G-Eval（忠实度 / 完整度 / 简洁度）—— 待运行

需 `DASHSCOPE_API_KEY`（云端千问 qwen3.8-max 裁判，仅评测用、不影响端侧离线）。设好后：
```
$env:DASHSCOPE_API_KEY="sk-..."; python eval/run_deepeval_clean.py
```
runner 会自动带上 L2 三个 G-Eval 指标并写回本目录。这才是正经 LLM-judge 忠实度
（比确定性接地率代理强，能判"内容是否被原文支撑、有无编造/跑题"）。

## 诚实边界

- L1 确定性、可复现，是判定依据；AnchorSupport=1.0 只保证 refs 锚点真实，**不等于内容语义忠实**
  （"张冠李戴"=词对关系错，L1 测不到，需 L2 或 DecisionOwner 侧证）。
- 参考金标为人工关键点（n=4，少）+ golden_v2 银标（n=30）；均非大规模 gold。
- 输入为干净转写（隔离 ASR 噪声），测的是摘要阶段本身，非端到端。
