# 资产清单（模型 / 数据 / 金标 / 机器）

> 代码之外、但项目离不开的东西：模型权重、数据集、金标、语料、venv。
> ⚠️ **标「E: 盘 / 本机」的会随本机清空而永久丢失**——交接人须在清空前转移，并在「交接去向」列填明去处。路径以交接时实测为准。

## 1. 板端 RK1828（`/userdata/...`，随板留存，但依赖板子在）

| 资产 | 路径 | 说明 |
|---|---|---|
| LLM 模型 Qwen3-4B ctx16k | `…/models/llm/v104/qwen3-4b-v104-ctx16k` | 四类文件 `.rknn`/`.weight`/`.tokenizer.gguf`/`.embed.bin` |
| ASR 模型 Qwen3-ASR-0.6B | `…/models/asr/qwen3-asr-0.6b-rknn` | encoder/llm 的 rknn/weight + tokenizer/embed |
| ASR runner（GCC10 编译） | `…/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo` | 常驻 batch runner 二进制 |
| 3D-Speaker + conda 环境 | `/userdata/3D-Speaker` + `/userdata/miniforge3/envs/3dspeaker` | CPU/Torch 说话人分离；VAD 已固化 `speech_noise_thres=0.2`（备份 `.vadbak`） |
| RKLLM server / runtime | `/usr/bin/rkllm3-server` + RKNN3 runtime 1.0.4 | 非 pip |
| 代码快照 + venv | `/userdata/meeting_agent1/mainline_<sha>/src` + `venvs/mainline_<sha>` | venv 须能 `import pypinyin` |
| 板端评测框架 | `/userdata/meeting_agent/evals/` | 成套 e2e 评测（勿另起炉灶）；`llm_judge.py` 里失效 key 待清 |
| 官方 TextGrid 金标 | `/userdata/meeting_agent/data/audio/train_L/TextGrid/`（32 个） | 评测事实真值（`.rttm` 是我方 3D-Speaker 自产、非金标） |
| 历史 pipeline 输出 | `/userdata/meeting_agent/evals/pipeline_outputs/e2e_trainL_full/`（~30 场） | 复用 ASR 结果的评测样本 |
| 输入音频 | `/userdata/meeting_agent/input/` | 测试音频 |

## 2. 交接人本机 E: 盘（⚠️ 清空即丢，**必须转移**）

**结论：E: 上的模型 / 数据集 / venv / ollama 几乎都能自行下载或按 `requirements` 重建，无需整盘搬运；真正需要保留的只有最后两项自产材料（需求调研、工作记录），且已大部入库。**

2026-09-11 实测（合计约 48 GB，但绝大多数可重新获取）：

| 资产 | 路径 | 实测大小 | 交接方式 |
|---|---|---|---|
| 模型合集 `Qwen3-4B` / `Qwen3-ASR-0.6B-hf` | `E:/models/` | 9.64 GB | **自行下载**（HuggingFace / modelscope：`Qwen/Qwen3-4B`、`Qwen/Qwen3-ASR-0.6B`） |
| `qwen3-4b-meetlora`（QLoRA adapter） | `E:/models/qwen3-4b-meetlora` | （含上） | **可弃**（4B 微调负结果产物） |
| golden 评测集 train_L | `E:/train_L` | 6.61 GB | **自行下载** AliMeeting（modelscope）；30 场选取清单见 `eval/golden_v2/out/*`（已入库），官方 TextGrid 随 AliMeeting，`.rttm` 我方自产可重跑 |
| 微调训练集 train_S | `E:/train_S` | 13.17 GB | **自行下载** AliMeeting（与 train_L 不相交子集） |
| embedding 模型 | `E:/modelscope` | 3.42 GB | **自行下载**（modelscope：bge-small-zh-v1.5 / Qwen3-Embedding-0.6B） |
| PC 评测/微调 venv | `E:/DevTools/venvs/pico-embed` | （E:/DevTools 9.28G） | **按 `requirements/requirements-pc-eval.txt` 重建** |
| Ollama + 模型 | `E:/ollama` + `E:/ollama-models` | 4.14 GB | **自行下载**：装 Ollama + `ollama pull qwen3:4b` |
| HF 缓存 | `E:/hf-cache` | 1.21 GB | **无需搬**（下载时自动重建） |
| 🔺 需求调研原件 | `E:/需求调研` | 1.02 GB | **须保留**：PRD 全套已入 `docs/需求调研/`；剩余 Gold 标注 / 6 家竞品详报 / 前端原型 HTML 未入库，按需拷仓库或网盘 |
| 🔺 工作记录 | `E:/工作记录` | ~几 MB | **须保留**：日报/周报/交接/架构图；已提炼进 `docs/技术演进.md`，原件是否另存由交接人定 |

> 注：E: 盘还有大量**与本项目无关**的目录（steam/SteamLibrary/WeGameApps、KiCad/Modelsim/Multisim、langchain、迅雷/微信/语雀等），转移时按上表白名单取即可。

## 3. 仓库内（随 git 走，相对安全）

| 资产 | 路径 |
|---|---|
| 自建银标 golden_v2（30 场） | `eval/golden_v2/out/*.golden.json` + `verify/` |
| 转写评测线结果 | `eval/transcription/_out/`、`eval/reports/*` |
| PRD 全套 | `docs/需求调研/` |
| 旧项目 + RKNN3 SDK PDF | `docs/reference/legacy-board-harness/` |

> ⚠️ 若 `eval/` 下这些**尚未提交**，本机清空前务必 commit（见 HANDOFF §十一）。

## 4. 实验机（`D:\Meeting_Agent_mainline`）

| 资产 | 路径 | 说明 |
|---|---|---|
| 已上传会议音频 | `runtime/meeting_library_agent1/meetings/*/source.wav` | 产品模式上传的 ~30min wav（~59MB/个） |
| Gateway 配置 | `runtime/gateway_settings_agent1.json` | 指向板端 `:18082` |
| 板端回传诊断 | `runtime/board-diagnostics/` | 历史诊断包 |
| poller | `ops/board-bridge/bridge_poll.py`（运行中） | **归属/开机自启须交接** |

## 5. 外部可重新获取

| 资产 | 来源 |
|---|---|
| AliMeeting 语料 | https://www.modelscope.cn/datasets/modelscope/AliMeeting |
| AISHELL-4 | https://www.aishelltech.com/newsinfo/2226596.html |
| RKNN3-Toolkit / Model Zoo | github.com/airockchip/rknn3-toolkit · rknn3-model-zoo（见 README §11.5） |
| RKNN3 Runtime / 预转换模型 / 受控网盘 | 收费/受控，见 README §11.5（凭据线下） |
