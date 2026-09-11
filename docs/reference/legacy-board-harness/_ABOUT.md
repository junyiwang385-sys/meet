# Legacy 板端 Harness 参考（`HawlsonZ/Meeting_Agent`）

这是当前 `meet` 系统的**板端前身**：一条只在 RK1828 上跑的生产 Harness（`meeting_harness` 包），**不含前端/Gateway**。当前 `src/meeting_agent/` 是它的后继（分层重构 + 前端 + Gateway + 产品化 + 评测）。

拉进来作**血脉与基础设施参考**（非当前运行代码，勿从这里启动）。已剔除 `.git`、`data/`（模型数据）、含失效密钥的 `llm_judge.py.txt`/`_source.txt` 与 `.tsd.backup` 备份。

## 值得看的部分

| 路径 | 用途 |
|---|---|
| `README.md` | 旧项目总说明：全链路、生产入口、上下文预算、产物权威性、评测、已知限制 |
| `docs/architecture.md` | **板端 Harness 机制权威文档**：端到端数据流、阶段边界、紧凑引用、上下文预算、**§5 历史一次性全量 → §6 滑动章节窗口（分章/摘要演进的关键）**、章节归并、full-summary、action-review、speaker batches、验证发布、resume |
| `prompts/README.md` + `prompts/meeting_summary_v32_zh.md` | Prompt 协议（`PROMPT_VERSION=meeting-summary.v3` / `PRODUCT_SUMMARY_VERSION=product-summary.v32`）——摘要提示词演进落点 |
| `scripts/README.md` | 脚本索引：segmentation（3D-Speaker+unknown 吸收）、Batch ASR、diarization/TextGrid 分析工具、model 转换在 `local_only`（gitignore） |
| `scripts/board/` `scripts/diarization/` | 板端 segmentation / Batch ASR 入口 + diarization padding/gap/CER 分析工具 |
| `meeting_harness/` | 旧生产包源码（`main/pipeline/product_summary/summary/chunking/transcript/validation/compat_export/llm/artifacts`）；注意同时有 `summary.py`(旧) 与 `product_summary.py`(新) = 演进痕迹 |
| `evals/` | 旧评测框架（VCSum + 真实音频 E2E，官方 TextGrid 金标，`deterministic_grader`/`llm_judge`） |
| `docs/rk1828_qwen_asr_llm_deployment_summary.md` | **模型转换 / RKNN3 runtime 部署历史**（ASR runner GCC10 编译、rkllm3-server、Qwen 四类模型文件） |
| `docs/rk1828_meeting_agent_issues_and_solutions.md` | 问题/实验/解决方案历史（基础设施排障） |
| `docs/resume_metrics_overview.md` | resume 与指标概览 |
| `docs/history/mainDoc.md` | legacy 综合记录 |
| `docs/Rockchip_*RKNN3_SDK_*.pdf` | Rockchip RK182X / RKNPU3 RKNN3 SDK v1.0.0 / v1.0.4 官方快速上手与 ReleaseNote（模型转换/runtime 一手参考） |

> 诚实边界：文档里的路径/模型/机器地址是**当时**状态，以当前 `meet` 仓库代码为准。`llm_judge.py` 里保留的 `maas.xgimi.com` 只是 env 默认 base_url、非密钥。
