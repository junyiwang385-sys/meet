# 项目交接文档（RK1828 端侧会议纪要系统）

> 面向**接手人**：从拿到项目到跑通一次端到端所需的一切。先读本文 → 再按需展开各专题文档（§十一）。
> 交接人离职在即，**本机（开发机）文件将被清空**，最终仓库迁到公司 **GitLab**。凡有价值的都必须先落进仓库/线下移交（见 §十二 防丢清单）。

---

## 一、这是什么

RK1828 NPU 上**离线**运行的会议纪要系统：一段会议录音 → 板端本地完成说话人分离 / 语音识别 / 转写整理 / 纪要生成 → 结构化可追溯纪要。三层：Windows 前端 + Windows Gateway + 板端 Board Agent/Harness。详见 [`README.md`](../README.md) 与 [`docs/技术演进.md`](技术演进.md)。

**当前成熟度（诚实）**：板端直连 Harness 全链路 5 组通过；前端→Gateway→板端→回前端端到端 1 次通过（548s/30min 音频）；前端 VAD 优化已固化上板。**未验**：1–2h 长会（项目卖点）、板端 4K 配置的系统化质量评测。PC 侧实验均为板端等价替代。

## 二、仓库与分支（接手第一件事）

- **当前**：origin = 个人 GitHub `https://github.com/junyiwang385-sys/meet.git`（交接人账号，**离职后有失权/消失风险**）。
- **目标**：迁到**公司 GitLab**。交接流程：实验机 `git pull`（从 GitHub 拿全）→ 加 GitLab remote → push 到 GitLab → 以 GitLab 为唯一权威库。
- **分支现状**：⚠️ **全部工作（180+ commit）在 `feature/transcript-postprocess`，从未合并到 `main`**；`origin/main` 是旧/空状态。另有散支 `feat/speaker-summary-ui`、`refactor/product-summary-split`。
  - **接手动作**：把 `feature/transcript-postprocess` 合并进 `main`（或在 GitLab 设为默认分支），废弃散支。别在 `main` 上继续开发前先确认它是最新的。
- **迁库后**：更新本文与 README 里的 origin 描述为 GitLab 地址。

## 三、机器与网络

| 角色 | 地址 | 用户 / 连接 | 谁维护（接手须确认） |
|---|---|---|---|
| 板端 RK1828 | `10.10.22.36`（内网） | `ssh linaro@10.10.22.36` | ？ |
| 实验机（Windows） | 内网 | 直连板端 + 跑 poller/Gateway/前端 | ？（**关键：poller 一停，本机遥控链就断**） |
| FT/构建服务器 | `10.10.22.40` | `ssh -p 2222 ubuntu@10.10.22.40` | ？ |
| 本机/开发机 | 校园网 | 经 GitHub 命令桥遥控（不直连内网） | 即将清空 |

- 查 IP：板端/服务器上 `ip addr` / `hostname -I`；实验机扫内网 `arp -a | findstr 10.10.22`。DHCP 可能漂移。
- **命令桥**（本机不直连板端时用）：本机写 `ops/board-bridge/commands/NNNN_*.txt` push → 实验机 `bridge_poll.py` 拉取执行 → 结果回 `results/`。见 [`ops/board-bridge/README.md`](../ops/board-bridge/README.md)。
- 详见 [`README.md` §十一 基础设施与运维](../README.md)。

## 四、凭据移交清单（⚠️ 线下交接，**不要写进仓库**）

接手人需要下列凭据，交接人**通过密码管理器/线下**移交，切勿提交到 git：

- [ ] 板端 `linaro@10.10.22.36` 密码或 ssh 私钥（实验机已配免密，换机器要重配 `ssh-copy-id`）
- [ ] FT 服务器 `ubuntu@10.10.22.40:2222` 凭据
- [ ] GitHub 账号（迁库期间过渡用）→ 迁到 GitLab 后以 GitLab 账号为准
- [ ] 公司 GitLab 仓库创建/推送权限
- [ ] 受控网盘（RKNN3 Runtime 收费件 / V1.0.5b2 库+头文件 / 预转换模型）访问方式（见 README §11.5）
- [ ] 若还需板端 LLM judge：换一把**有效** MaaS/Anthropic key 走环境变量（板端 `llm_judge.py` 里那把 `sk-8Rja…` 已失效，交接前应清除）

## 五、环境安装

- **板端 Harness**：隔离 venv 里 `pip install -r requirements/requirements-board.txt`（关键是 `pypinyin`）；另有 3D-Speaker conda 环境 + ASR runner + rkllm3-server（非 pip，见资产清单）。
- **PC 评测/微调**：`requirements/requirements-pc-eval.txt`（torch cu128 + transformers/peft/trl/bitsandbytes + jiwer/pyannote + funasr）。实测在 `pico-embed` venv。
- **前端**：`cd frontend/meeting-agent-ui-v1 && npm install`（`package-lock.json` 已锁；Node ≥ 20）。

## 六、跑通一次（验证接手成功）

1. **板端直连 Harness（最小链路）**——见 README §六.1，`python -m meeting_agent.harness.main --source-audio … --out-dir … --overwrite --enrichment`，再 `run_report`。看 `meeting_result.json status=ok` + 6 阶段 succeeded。
2. **前端→Gateway→板端→回前端**——在实验机跑 `ops/launcher/start-demo.bat`（起 Gateway:8787 + 前端:5173 + 开浏览器）；或无人值守 `python ops/e2e/gateway_e2e_client.py --audio <本地wav>`。看轮询走到 `meeting_ready`。
3. **评测**——`python -m pytest tests`（软件回归）；`eval/` 下 golden_v2 / transcription（需 PC eval 环境 + 金标，见资产清单）。

### 六.4 验收基线（"绿"长什么样）

| 项 | 命令 | 通过标准 |
|---|---|---|
| 软件回归 | `python -m pytest tests` | unit/contract/integration 全绿 |
| 前端构建 | `cd frontend/… && npm run build` | `tsc -b && vite build` 无错 |
| 板端直连全链路 | `python -m meeting_agent.harness.main …` + `run_report` | `meeting_result.json status=ok`；`stage_status.json` 6 阶段 succeeded；`run_report` 里 `server.loaded_once=true`；无阻断性红旗 |
| 端到端（Gateway） | `python ops/e2e/gateway_e2e_client.py --audio <wav>` | 轮询走到 `state=completed / stage=meeting_ready`，`GET /result` 200 |
| 摘要质量（评测，需金标+PC 环境） | `eval/golden_v2/`（打分脚本） | **over_decision=0**（不编造决策）；核心事实召回 ~0.57（板端 A0 基线，非硬阈值） |
| 转写质量 | `eval/transcription/`（点3/点4） | 点3 ASR CER ~0.15（金标切分）；点4 端到端 CER ~0.44（VAD 固化后）；均为**诊断指标非产品门槛** |

> 注意：项目**不冻结**准确率/时延等硬阈值（PRD 明确），以上是「当前基线值」，用于判断"没跑坏"，不是验收合格线。长会（1–2h）尚无基线（未验）。

## 七、资产（模型 / 数据 / 金标）

E: 盘上的模型/数据集/venv/ollama **几乎都能自行下载或按 `requirements` 重建，无需整盘搬运**（模型走 HF/modelscope、语料走 AliMeeting、venv 按 `requirements-pc-eval` 重建、`ollama pull qwen3:4b`）。**真正须保留的只有自产材料**：`E:/需求调研`（PRD 已入库，剩余 Gold/竞品/原型按需）与 `E:/工作记录`（已提炼进技术演进）。清单与下载来源见 [`docs/ASSET-INVENTORY.md`](ASSET-INVENTORY.md)。

## 八、待办 / 已知问题 / 已弃

见 [`docs/OPEN-ITEMS.md`](OPEN-ITEMS.md)（热词 C++ 板端落地、长会未验、Gateway 415 不 drain 体、Board Agent schema_version 未校验、speaker chunk/merge 未做、4B 微调负结果已弃 等）。后续 roadmap 见 [`docs/优化方向.md`](优化方向.md)（微调 / 领域知识库·RAG 专名 / 专用分章模型 / 前端会议资料写入）。

## 九、环境 / 网络 / 部署踩坑（部落知识，接手必看）

这些是散在实操里、文档不写就会重复踩的坑：

- **板端部署禁 scp .py**：实验机有 **DLP 透明加密**，`scp` 传 `.py` 会被塞 `%TSD-Header%` 变密文 → 板端 import 报空字节。改**板端从 GitHub/GitLab 直拉**（sparse + shallow），或 base64 编码传输。
- **本机连不到内网**：mihomo 代理造成"假 TCP"、以太网无内网路由 → 本机 ping/ssh 板端不通是常态，**一律走命令桥经实验机**。
- **命令桥自愈**：poller `git pull` 失败（unmerged）会 `reset --hard` 上游自愈；会丢本机未推的本地提交（只可能是 result.out，重跑即可）。**改文档后本机 `git pull` 会因未提交改动失败 → 用 `git fetch` + `git show origin:<path>` 读结果**。
- **NPU 单大模型**：板端同一时刻只能跑一个大模型，ASR 与 LLM **串行调度**（并发会 `rknn3_create_mem timeout`）。
- **ASR runner 编译**：必须 GCC-ARM **10.3**（GCC13 产物 glibc 不兼容板端）；FFTW 加 `-no-pie`。
- **VAD 真相**：AliMeeting 是**话语级**标注（既松又漏），帧级 miss/DER 会失真、被高估约 5×；量 VAD 漏检要用逐句实义覆盖率（当前 `speech_noise_thres=0.2` 已固化上板，整句丢 28%→9%）。
- **4B 能力边界**：强检索/抽取、弱归纳（≤30%）/篇章/低频；设计铁律见 `CLAUDE.md`（确定性搭骨架、4B 只做受控抽取、不用 few-shot 会 echo 示例）。
- **前端上传 415**：Windows 把 .wav 报成 `audio/wave`，Gateway 只认 `audio/wav` → 前端已改成按扩展名发 `audio/wav`（`gateway-meeting-api.ts`），服务端 415 不 drain 体的隐患见 OPEN-ITEMS。

## 十、文档地图

| 文档 | 用途 |
|---|---|
| [`README.md`](../README.md) | 项目总览 / 架构 / 入口命令 / 运行 / 端口接口 / 产物 / 基础设施(连接·模型转换·RKNN 资料) |
| [`CLAUDE.md`](../CLAUDE.md) | 4B 小模型能力边界 + 9 条设计原则（改摘要前必读） |
| [`docs/技术演进.md`](技术演进.md) | 全链路演进架构图 + 每步方案演进（分章/摘要…） |
| [`docs/实验与各阶段成果.md`](实验与各阶段成果.md) | 分阶段实验/指标/结论（阶段一~十三） |
| [`docs/需求调研.md`](需求调研.md) + `docs/需求调研/` | 需求总结 + MVP PRD 导读 + PRD 全套 |
| [`docs/OPEN-ITEMS.md`](OPEN-ITEMS.md) | 待办 / 已知问题 / 已弃 |
| [`docs/ASSET-INVENTORY.md`](ASSET-INVENTORY.md) | 模型/数据/金标/机器资产清单 |
| [`docs/inventory/2026-09-04_RK1828板端目录与全链路文件说明.md`](inventory/) | 板端目录/路径/重跑清单（板端权威手册） |
| [`docs/operations/`](operations/) | 部署与模型转换历史 |
| [`docs/reference/legacy-board-harness/`](reference/legacy-board-harness/) | 板端前身项目全份 + RKNN3 SDK PDF |
| `requirements/requirements-board.txt` · `requirements-pc-eval.txt` | 依赖锁 |

## 十一、本机清空前 · 防丢 checklist

交接人在清空本机前，逐条确认（否则永久丢失）：

- [ ] 本轮所有文档已 commit + push（README/docs 全套/reference/CLAUDE/requirements）——**这是最紧急项**
- [ ] `eval/` 下要保留的实验产物（golden_v2/out 金标、transcription 结果、reports）已决定去留并提交需要的
- [ ] 仓库已 push 到 GitLab 并验证可 clone
- [ ] E: 盘：模型/数据集/venv/ollama 可自行下载重建（无需搬）；仅 **`E:/需求调研`、`E:/工作记录`** 两项自产材料确认已入库或另存（见 ASSET-INVENTORY）
- [ ] 凭据清单（§四）已线下移交接手人
- [ ] 实验机 poller / Gateway 的归属与开机自启已交接（否则遥控链断）
- [ ] 板端那把失效 MaaS key 已清除
- [ ] 交接人**口头/记忆里**的知识已尽量写进本文 §九与各文档（离职后无法再问）
