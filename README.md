# RK1828 端侧会议纪要系统（meet）

在 **RK1828 NPU 开发板**上离线运行的一条完整会议纪要链路：一段会议录音进去，板端本地完成说话人分离、语音识别、转写整理、纪要生成与增强，产出可追溯、可校验的结构化会议纪要。**全程离线、音频不出局域网**，主打隐私与端侧部署。

- **平台**：RK1828 NPU（RKNN3 1.0.4 runtime）
- **模型**：Qwen3-ASR-0.6B（语音识别）+ 3D-Speaker / CAM++（说话人分离）+ 量化 Qwen3-4B ctx16k（W4A16，纪要生成）
- **形态**：Windows 前端（React 19 + Vite）+ Windows Gateway（本地网关）+ 板端 Board Agent / Harness
- **包名**：`meeting-agent`（源码在 `src/`，Python ≥ 3.11）；前身见 [`docs/reference/legacy-board-harness/`](docs/reference/legacy-board-harness/)

---

## 一、系统架构

三层部署（音频只在局域网内从前端流向开发板）：

```text
Windows 前端 (React19+Vite, :5173)  ──或── Gateway 内置单页 UI (/app)
      │  HTTP /api/*
Windows Gateway (:8787)                     本地网关：上传/状态投影/结果回投/草稿/正式版/存储
      │  HTTP /v1/*  (LAN)
板端 Board Agent (10.10.22.36, 代码默认 :18080 / 隔离部署 agent1 :18082)
      │
Board Harness Worker → Harness main (python -m harness.main)
      │
   ┌─ 1 segmentation       3D-Speaker/CAM++ · VAD · unknown 吸收/兜底 → 01_segments/
   ├─ 2 batch_asr          Qwen3-ASR 常驻 batch runner → 02_batch_asr/
   ├─ 3 transcript_prepare  canonical transcript/timeline + 确定性重叠去重
   ├─ 4 llm_summary        RKLLM server(:18245) 起 Qwen3-4B：块摘要→概览/章节→发言人/待办 → 03_llm_summary/
   ├─ 5 enrichment         复用同一 RKLLM session：关键词/问答/金句/决策/层级大纲
   └─ 6 compat_export      兼容格式导出 → 04_compat_export/ + 原子发布 meeting_summary/frontend/display
      │
   结果回投 Board Agent → Gateway(转产品 meeting-result.v1) → 前端展示 → 人工核对 → 正式版导出
```

> 全链路每一步「方案怎么演进」（分章 / 摘要 / ASR / 分离 …）见 [`docs/技术演进.md`](docs/技术演进.md) 的**全链路演进架构图**。

## 二、核心设计哲学：围绕 4B 小模型的能力边界

不是「堆一个大模型」，而是**认清 4B 的能力边界，用确定性流程把它不擅长的事拆掉**：

- 4B **强**：检索、聚合、二分类判断、schema 引导的受控抽取；
- 4B **弱**：自主归纳（≤30%）、篇章级理解、精确低频信息（数字/专名易漏）；
- 因此：**确定性 DAG 搭骨架**（标准化/VAD/分离/切分/去重/分章边界/范围归并/校验发布）→ 4B 只做它强的（map 块摘要 / reduce 概览 / speaker / action 四类节点）→ 全局靠显式构造（紧凑引用 / carryover 压缩摘要 / reduce）→ 输出强 schema 约束（不用 few-shot）→ 分层隔离（无损喂下游 / 有损只展示 / 证据锚原文）。

> 完整能力边界与 9 条设计原则见 [`CLAUDE.md`](CLAUDE.md)（长期约束，改摘要环节前必读）。注：`CLAUDE.md` 头部写的 `ctx=8k` 为早期值，当前默认 **ctx=16384**（以代码为准）。

## 三、目录结构

| 路径 | 内容 |
|---|---|
| `src/meeting_agent/harness/` | 全链路主编排：`main.py`(CLI/参数)、`pipeline.py`(6 阶段)、`lifecycle.py`(阶段状态/收尾/artifact)、`errors.py`、`artifacts.py` |
| `src/meeting_agent/stages/` | `transcript` / `postprocess`(去重·纠错·顺滑) / `topic_segmentation`(A层确定性分章) / `product_summary`(块摘要·概览·章节·发言人·待办) / `enrichment` / `summary_profiles`(领域画像) / `validation`(证据校验) / `compat_export` / `display` |
| `src/meeting_agent/llm/` | `llm.py`(RKLLM server 生命周期/请求/计数) · `chunking.py`(预算/分块) · `ollama_session.py`(PC 侧鸭子对齐后端，用真 stage 代码复现板端) |
| `src/meeting_agent/adapters/board/` | `board_agent_api_v0.py`(板端 HTTP Agent) · `board_harness_worker_v0.py`(Harness 子进程编排) · `asr/`·`minutes/`·`smoke/`·`llm/`(板端脚本) |
| `src/meeting_agent/adapters/gateway/` | `meeting_agent_gateway_v0.py`(网关) · `gateway_settings.py` · `meeting_library.py`(SQLite) · `gateway_storage.py` · `meeting_result_adapter.py`(v2→产品v1) · `formal_export.py`(正式版) · `meeting_agent_gateway_ui_v0.html`(内置 UI) · `funasr/`(PC FunASR 原型) |
| `src/meeting_agent/observability/` | `runlog`(run_events/manifest) · `metrics` · `error_report` · `run_report`(聚合报告+优化红旗) |
| `src/meeting_agent/contracts/` | `identity`(trace/meeting/task/run) · `errors`(归一化/重试语义) · `results`(schema 版本常量) |
| `src/meeting_agent/storage/` | `artifacts.py`：`HarnessPaths` 输出目录结构、原子写、SHA-256 |
| `src/meeting_agent/cli/` | 3 个瘦包装（harness/board_agent/gateway） |
| `frontend/meeting-agent-ui-v1/` | React 19 + Vite 8 + TanStack Query 5 + react-router 7 前端 |
| `schemas/` | meeting/transcript/summary/result/observability 分组 schema（+ 根目录兼容平铺） |
| `prompts/` | 板端 minutes/overview map-reduce 中文提示词模板 |
| `eval/` | 评测：`golden_v2/`(银标+对标) · `transcription/`(点1-4) · `finetune/`(QLoRA) · `reports/` |
| `ops/` | `board-bridge/`(GitHub 命令桥) · `e2e/`(端到端客户端) · `launcher/`(桌面启动器) |
| `docs/` | 架构/契约/运维/排障/清单/参考 + 技术演进/实验成果/需求调研（见 §八） |
| `manifests/` `runtime/` `snapshots/` | 目录 SHA-256 校验清单 / 本地运行脚手架 / 板端部署快照(只读参考) |

## 四、入口点与命令

`pyproject.toml` 定义 4 个 console_scripts：

| 命令 | 模块 | 作用 |
|---|---|---|
| `meeting-agent-harness` | `harness.main` | 全链路 Harness（板端主入口） |
| `meeting-agent-run-report` | `observability.run_report` | 从 out-dir 聚合 `run_report.md/json`（时延/token 经济学/质量/内存/优化红旗） |
| `meeting-agent-board-agent` | `adapters.board.board_agent_api_v0` | 板端 HTTP Agent 服务 |
| `meeting-agent-gateway` | `adapters.gateway.meeting_agent_gateway_v0` | Windows 本地网关 |

也可 `python -m meeting_agent.harness.main …`。板端部署常把包平铺为 `/userdata/meeting_agent1/mainline_<sha>/src`，模块名即 `meeting_agent.harness.main`。

**`harness.main` 关键参数（默认值）**：`--source-audio`/`--out-dir`(必填)、`--overwrite`|`--resume`(互斥)、`--ctx 16384`、`--predict 3072`、`--max-tokens 3072`、`--input-chars-per-token 1.55`（板端 worker/run_report 校准用 1.3）、`--port 18245`(RKLLM server)、`--temperature 0.0`、`--enrichment`(默认开，`--no-enrichment` 关)；板端路径 `--3dspeaker-dir /userdata/3D-Speaker`、`--asr-dir …/rknn_Qwen3_ASR_batch_demo`、`--model-dir …/qwen3-4b-v104-ctx16k`、`--server /usr/bin/rkllm3-server`。完整以 `--help` 为准。

> ⚠️ **依赖**：`pyproject` 的 `dependencies=[]` 未声明，但 `stages/postprocess.py` 顶层 `import pypinyin`（硬依赖，主链路必装）；`stages/enrichment.py` 的 `jieba` 为可选。运行环境须先 `pip install pypinyin`。

## 五、端口与关键接口

| 服务 | 端口 | 说明 |
|---|---|---|
| 前端 Vite dev | `5173` | `vite --host 127.0.0.1`（Gateway CORS 只放行 127.0.0.1:5173 / localhost:5173） |
| Windows Gateway | `8787` | 本地网关（`DEFAULT_BOARD_URL=http://10.10.22.36:18080`，隔离部署经 settings 指向 `:18082`） |
| 板端 Board Agent | `18080`(代码默认) / `18082`(agent1 隔离部署) | HTTP `/v1/*` |
| Harness 内部 RKLLM server | `18245` | 每次运行内部起，非 Agent 端口 |

- **Board Agent `/v1/*`**：`GET /v1/health`、`POST /v1/tasks`、`GET /v1/tasks/{id}`、`POST /v1/tasks/{id}/cancel`、`GET /v1/tasks/{id}/result`、`PUT /v1/tasks/{id}/audio`。`task_kind` 三态：`transport_probe`(通信探针) / `audio_upload_probe`(上传+SHA-256 校验) / `harness_meeting_v0`(上传后后台起 Harness)。**单任务锁**：一次只一个活动任务。
- **Gateway `/api/*`**（20+ 端点）：`/api/info`、`/api/board/health`、`GET|POST /api/meetings`、`/api/meetings/{id}`(+`/result`、`/audio`、`/draft`、`/finalize`、`/exports`、`/cancel`、`/retry`、`/rescan`)、`/api/settings`、`/api/storage`、`/api/system/status`、`GET /app`(内置 UI)。会议元数据用 **SQLite** 持久化（`runtime/meeting_library/`）；能力矩阵含 meeting_library/local_upload/draft/finalize/diagnostics（pc_record/board_record/audio_delete=false）。

## 六、运行方式

### 1. 板端直连 Harness（最小链路）

```bash
SNAPSHOT=/userdata/meeting_agent1/mainline_cc9d83e
PY=/userdata/meeting_agent1/venvs/mainline_cc9d83e/bin/python   # 须能 import pypinyin
export PYTHONPATH=$SNAPSHOT/src
$PY -m meeting_agent.harness.main \
  --source-audio /userdata/meeting_agent/input/<meeting>.wav \
  --out-dir /userdata/meeting_agent/output/<run>/harness \
  --meeting-id g1 --overwrite --enrichment
$PY -m meeting_agent.observability.run_report <out-dir>
```

### 2. 前端 → Gateway → 板端 → 回前端（完整产品链路）

一键启动器（实验机，见 [`ops/launcher/`](ops/launcher/)）：先跑一次 `create-desktop-shortcut.bat`，之后双击桌面「Meeting Agent Demo」= 起 Gateway(:8787) + Vite 前端(:5173) + 开浏览器。或手动：

```bat
ops\board-bridge\run\start_gateway.bat      :: Gateway :8787，settings=gateway_settings_agent1.json（board :18082）
ops\board-bridge\run\start_frontend.bat     :: Vite :5173 指向 Gateway :8787
```

无人值守验证用 [`ops/e2e/gateway_e2e_client.py`](ops/e2e/gateway_e2e_client.py)（建会→上传→轮询→拉结果，与浏览器同一组 `/api/*`）。

## 七、产物结构与版本契约

一次运行的 out-dir（`storage/artifacts.py::HarnessPaths`）：

```text
<out-dir>/
├── run_config.json  run_manifest.json  run_events.jsonl  run_metrics.json
├── error_report.json  stage_status.json
├── timeline.txt  meeting_summary.json  meeting_frontend.json  meeting_display.txt  meeting_result.json
├── logs/  runtime/(memory_*)
├── 01_segments/     02_batch_asr/     03_llm_summary/(canonical_segments/plan/validation/enrichment/server_status/blocks/requests)     04_compat_export/
```

> `meeting_result.json` 是运行状态权威外壳；只有它 `status:"ok"` + 最终 validation 通过 + summary/frontend/display/兼容导出同源，才算完整成功。单次 HTTP 成功不等于会议已发布。transcript_prepare / enrichment 无独立编号目录（产物分别落 `timeline.txt`+`03_llm_summary/`）。

版本契约（选摘）：`meeting-result.v2`、`meeting-summary.v1`、`run-{event,manifest,metrics}.v1`、`error-report.v1`、`meeting-diagnostics.v1`、`meeting-compat.v1`、`product-summary.v25`、`topic-segmentation.v2`、`postprocess.v1`、`gateway-settings.v1`、`formal-minutes.v1`；`HARNESS_VERSION=2.0.0`。

## 八、文档导航

| 文档 | 用途 |
|---|---|
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | **交接总入口**：从零上手 runbook / 仓库分支 / 凭据清单 / 机器 / 踩坑 / 本机清空前防丢清单 |
| [`CLAUDE.md`](CLAUDE.md) | 小模型能力边界 + 9 条设计原则（长期约束，必读） |
| [`docs/技术演进.md`](docs/技术演进.md) | **全链路演进架构图** + S1→S12 演进 + 关键决策表 |
| [`docs/实验与各阶段成果.md`](docs/实验与各阶段成果.md) | 分阶段实验/指标/结论（阶段一~十三，含端到端实测） |
| [`docs/需求调研.md`](docs/需求调研.md) + [`docs/需求调研/`](docs/需求调研/) | 需求总结 + MVP PRD 导读；PRD 全套原文 |
| [`docs/OPEN-ITEMS.md`](docs/OPEN-ITEMS.md) | 待办 / 已知问题 / 已弃（负结果别重踩） |
| [`docs/优化方向.md`](docs/优化方向.md) | 后续 roadmap：微调 / 领域知识库·RAG 专名 / 专用分章模型 / 前端会议资料写入 |
| [`docs/ASSET-INVENTORY.md`](docs/ASSET-INVENTORY.md) | 模型/数据/金标/机器资产清单（含 E: 盘须转移项） |
| `requirements/requirements-board.txt` · `requirements-pc-eval.txt` | Python 依赖锁（板端最小 + PC 评测/微调） |
| [`docs/inventory/2026-09-04_RK1828板端目录与全链路文件说明.md`](docs/inventory/) | 板端目录/模型/脚本路径/重跑清单（板端权威手册） |
| [`docs/operations/`](docs/operations/) | 部署与**模型转换**（RKNN3 1.0.4、ASR runner GCC10 编译、rkllm3-server、Qwen 四类模型文件） |
| [`docs/reference/legacy-board-harness/`](docs/reference/legacy-board-harness/) | **板端前身项目**（`HawlsonZ/Meeting_Agent`）全份：旧 Harness 源码、`architecture.md`、prompt 协议 v32、diarization 工具链、Rockchip RKNN3 SDK PDF、部署/问题历史 |

## 九、当前验证状态（截至 2026-09-11）

- ✅ **板端直连 Harness 全链路**：2026-09-03 跑 5 组（~31–35min 音频），6 阶段全 succeeded，总耗时 ~8–9min，内存峰值 ~2.6–2.7GB，`loaded_once=true`。
- ✅ **前端→Gateway→板端→回前端 端到端**：2026-09-11 完整往返实测成功（30min 音频，548s，6 阶段推进到 `meeting_ready`，结果+artifact_refs 回投）。补齐了前身/交接一直遗留的最后一环。
- ✅ **前端 VAD 优化已固化上板**：整句丢 28%→9%（板端 g1）、端到端 CER 0.56→0.44、全 30 场 20.7%→7.3%。
- 🔬 **评测体系**：`eval/golden_v2/`（银标 + 对标飞书/通义，唯一强项 over_decision=0）、`eval/transcription/`（标准口径点1-4，jiwer/pyannote）。
- ⚠️ **诚实边界**：PC 侧实验为板端**等价替代**（Ollama/transformers/modelscope），方法论可信、绝对值板端会有差异；1–2h 超长会尚未真跑；4B 微调实验为**负结果**（不粉饰）。详见 `CLAUDE.md` §四 与 `docs/实验与各阶段成果.md`。

## 十、板端遥控（命令桥）

本机/开发机不直连内网板端，经 GitHub 命令信箱遥控（实验机轮询执行）：

```text
本机(写命令 push) ──GitHub── 实验机(轮询 pull→执行→push 结果) ──ssh/HTTP── 板端 10.10.22.36
```

用法见 [`ops/board-bridge/README.md`](ops/board-bridge/README.md)。

## 十一、基础设施与运维（连接 / 模型部署转换 / RKNN 资料）

### 11.1 网络拓扑与机器

| 角色 | 地址 | 用户 | 连接方式 | 说明 |
|---|---|---|---|---|
| 板端 RK1828 | `10.10.22.36`（LAN，内网） | `linaro` | `ssh linaro@10.10.22.36` | Board Agent 代码默认 `:18080`、隔离部署 agent1 `:18082`；历史 IP 曾为 `.26/.32/.36`，**以当前实测为准** |
| 实验机（Windows） | LAN | — | 直连板端 + 本地跑 Gateway/前端/poller | 本机/开发机连不到板端，全部经它中继 |
| FT / 构建服务器 | `10.10.22.40` | `ubuntu` | `ssh -p 2222 ubuntu@10.10.22.40` | 交叉编译 / 实验（WSL），**目前在用** |
| 本机 / 开发机 | 校园网（有公网 IP） | — | 经 GitHub 命令桥遥控（§十） | **不直连内网** |

### 11.2 如何查看 IP

- **在板端/服务器本机上**：`ip addr show`（或 `hostname -I`），取 `10.10.22.x` 那个内网地址；也可 `ip route` 看默认网关判断网段。
- **从实验机扫内网**：`arp -a | findstr 10.10.22`（或 `for /L` ping 段 + `arp -a`）列出在线设备；已知则直接 ssh。
- ⚠️ 内网多为 DHCP，IP 可能变动；连不上时先重新查 IP，再更新 `ops/board-bridge/run/*.bat`、`runtime/gateway_settings_agent1.json` 里的板端地址。

### 11.3 如何连接

- **实验机 → 板端**：`ssh linaro@10.10.22.36`。poller 是非交互的，**必须先做免密**（在实验机执行一次 `ssh-copy-id linaro@10.10.22.36`）；之后 `ssh linaro@10.10.22.36 "远程命令"` 免密执行。见 `ops/board-bridge/README.md`。
- **实验机 → FT/构建服务器**：`ssh -p 2222 ubuntu@10.10.22.40`。
- **本机 → 板端（不直连）**：把命令写进 `ops/board-bridge/commands/NNNN_*.txt` push，由实验机 poller 拉取执行、结果回传 `results/`（§十）。
- 凭据（密码/密钥）不写入本仓库；用 ssh key / 免密，勿在文档或代码里硬编码。

### 11.4 模型部署与转换

权威步骤见 [`docs/operations/rk1828_qwen_asr_llm_deployment_summary.md`](docs/operations/) 与 [`docs/reference/legacy-board-harness/docs/`](docs/reference/legacy-board-harness/docs/)（含 Rockchip RKNN3 SDK v1.0.0 / v1.0.4 PDF）。要点：

- **Runtime**：RK1828 装 RKNN3 runtime **1.0.4**（从 1.0.0 升级）；板端库 `/usr/lib/librknn3_api.so`，服务 `rknn3.service`。
- **LLM（Qwen3-4B ctx16k，W4A16）**：需四类文件 `.rknn` / `.weight` / `.tokenizer.gguf` / `.embed.bin`；用 RKNN3 toolkit 1.0.4 转换（脚本如 `convert_qwen3_v100_ctx.sh` + `export_qwen3_*` 指定 ctx=16384）；板端 `/usr/bin/rkllm3-server` 加载（不另编 C++ runner）。板端模型目录 `…/models/llm/v104/qwen3-4b-v104-ctx16k`。
- **ASR（Qwen3-ASR-0.6B）**：用 **`rknn3-model-zoo` v1.0.4** 的 `examples/Qwen3_ASR`（注意是带 3 的 `rknn3-model-zoo`）；**必须用 ARM GNU 10.3（GCC10）交叉编译**——apt GCC13 产物依赖 `GLIBC_2.38`/`GLIBCXX_3.4.32`，板端只有 `GLIBC_2.36` 会跑不起来；FFTW 需 `-no-pie`。输出 `rknn_qwen3_asr_batch_demo`（常驻 batch runner）。板端模型目录 `…/models/asr/qwen3-asr-0.6b-rknn`。
- **部署布局 / 重跑清单**：见 [`docs/inventory/2026-09-04_RK1828板端目录与全链路文件说明.md`](docs/inventory/)（板端目录、共享脚本、venv、最小文件集）。
- **踩坑**：SenseVoice RKNN 导出/算子在板端出不了正确结果（已弃，改 Qwen3-ASR）；同一时刻 NPU 只跑一个大模型（ASR 与 LLM 串行调度，避免 `rknn3_create_mem timeout`）。

### 11.5 RKNN 相关资料与网盘

（来源：前身项目 `docs/reference/legacy-board-harness/docs/history/mainDoc.md`「仓库和网盘」；典型流程=PC 用 RKNN3-Toolkit 转 RKNN → 板端 RKNN3 Runtime 推理）

| 资源 | 链接 | 说明 |
|---|---|---|
| **RKNN3-Toolkit**（PC 端模型转换/推理/评估） | https://github.com/airockchip/rknn3-toolkit | **公开**；LLM/ASR 转 RKNN 用 |
| **RKNN3 Model Zoo**（含 `examples/Qwen3_ASR`） | https://github.com/airockchip/rknn3-model-zoo | **公开**；ASR runner 源码 + export 脚本；须用 **v1.0.4**（v1.0.0 无 Qwen3-ASR 示例） |
| RKNN3 Runtime（板端运行时库 + `rkllm3-server`） | RK 官方提供，**收费**（非公开下载） | 板端 C/C++ 接口，部署 RKNN 模型 |
| 官方预转换模型（Lenovo box） | https://console.box.lenovo.com/l/H1fig1 | 仅 **ctx2048**，不满足会议长输入 → 其余 ctx 需自行按 §11.4 重新转换并设 `max_ctx_len` |
| 受控网盘（V1.0.5b2 动态库 + 头文件等） | **访问方式与凭据未公开** | 受控共享资源；前身文档原话「访问方式和凭据不在仓库文档中保存」 |
| Rockchip RKNN3 SDK 官方文档 PDF | 已入库 `docs/reference/legacy-board-harness/docs/Rockchip_*.pdf` | v1.0.0 Quick Start / ReleaseNote、v1.0.4 ReleaseNote |
| 语料数据集 | AliMeeting: https://www.modelscope.cn/datasets/modelscope/AliMeeting · AISHELL-4: https://www.aishelltech.com/newsinfo/2226596.html | 评测/验证语料 |

> Toolkit 与 Model Zoo 为公开 GitHub 仓库；Runtime 收费、受控网盘凭据未公开——如需内部网盘的具体链接/提取码，按各自访问渠道获取，不硬编码进仓库文档。

## 十二、边界

- 旧兼容源码与历史归档在 `D:\Meeting_Agent_legacy`；完整回滚基线在 `D:\Meeting_Agent_fresh`。
- 原会议音频、SQLite、失败证据与运行日志未随源码复制。
- 板端「新代码快照 + 共享运行资源」部署，重跑前须核对共享脚本/模型/3D-Speaker 环境版本一致（见板端全链路说明）。
- token 预算为字符比例**启发式估算**，非严格 tokenizer 计数；发言人超预算按时间最长前缀截断（未做 chunk/merge）；匿名 speaker 不映射真实姓名；ASR 语义错误会进入下游事实输入。
