# 待办 / 已知问题 / 已弃（OPEN ITEMS）

> 给接手人的「现在到哪、还差什么、别重复踩什么」。截至 2026-09-11。

## ✅ 已完成并验证

- 板端直连 Harness 全链路 5 组（2026-09-03，6 阶段 succeeded，~8-9min，内存 ~2.7GB，`loaded_once`）。
- 前端→Gateway→板端→回前端 端到端 1 次（2026-09-11，30min 音频 548s，走到 `meeting_ready`）。
- 前端 VAD 优化固化上板（`speech_noise_thres` 0.6→0.2，整句丢 28%→9%，端到端 CER 0.56→0.44，全 30 场泛化）。
- 评测线：golden_v2 银标 + 对标飞书/通义（over_decision=0 唯一强项）；transcription 点1-4（jiwer/pyannote）。
- 工程设施：命令桥、桌面启动器、e2e 客户端；结构化日志迁移 P1/P2/P3/P5（P4 部分，见下）。

## 🐞 已知问题 / bug（待修）

| 问题 | 现状 | 建议修法 |
|---|---|---|
| Gateway 上传前置拒绝不 drain 请求体 | 415/413 在读体前返回并关连接 → 客户端 `ERR_CONNECTION_ABORTED` → 前端误报"本地服务未链接"。前端已按扩展名发 `audio/wav` 绕开 | 服务端 415/413 前先读完（或按 Content-Length skip）请求体再回错；并把 `audio/wave` 等加进 `AUDIO_CONTENT_TYPES` |
| Board Agent `schema_version` 只透传不校验 | P4 计划要求版本校验，未实现 | `_safe_diagnostics` 加 `== 期望版本 else reject` |
| `return_code` 未全统一 | canonical 路径已统一，遗留 `adapters/board/minutes/*`、`smoke/*` 仍用 `exit_code` | 收敛到 `return_code` |
| `retry_scope` 只在 Gateway 层 | harness 错误不产出，易误解为同处产出 | 文档/代码澄清或下沉 |
| identity 不含 `source_sha256` | 哈希以 `source_audio_sha256` 存 manifest/result | 如需统一入 identity 块 |
| product_summary 事件 / board_agent 投影 缺独立单测 | 仅集成测试 `test_p0_diagnostics.py` 间接覆盖 | 补 unit |
| speaker 超预算只前缀截断 | 未做 chunk/merge，长发言人漏后半段 | 实现 speaker chunk/merge |

## 🔲 未完成 / 待验（功能与验证缺口）

- **长会 1–2h 端到端从未真跑**（项目卖点）；>30k token 分层方案只有设计、无实测。**接手优先补这个**。
- 板端 **4K 输出配置的系统化质量评测**（README 说以 4K 为准，但质量评测未系统跑）。
- 稳定性 / 内存泄漏（当前单轮、低置信）。
- over_decision / 忠实度评测**映射进板端 `evals/` 框架**（板端已有成套 e2e 评测框架，接管扩展，别另起炉灶）。
- 产品流 finalize/exports/draft 正式版闭环端到端未全验（Gateway `finalize` 能力曾返回 404）。

## ⏸️ 已验证可做但未落地（parked，有明确方案）

- **热词偏置板端 C++ 落地**：PC 已验证 GO（B-WER 0.186→0.083、echo=0）。板端落地 = 改 `rknn3-model-zoo/examples/Qwen3_ASR/cpp/qwen3_asr.cc`（prompt 构造 ~184 行起改成动态 prefix + `--hotwords`）→ GCC10 交叉编译 → 换板二进制 → int4 验证。词表须来自会前 metadata（参会名单/议程），从答案抠=注水。优先级中。
- VAD「紧致参考」（词级强制对齐做精确 miss 量化）——可选，AliMeeting 话语级标注给不了。

## ❌ 已弃 / 不做（负结果，别重复踩）

- **4B 摘要微调（QLoRA）**：负结果 **召回 0.167→0.024**，8G 显存约束（数据滤到 17 对 + 推理截断）+ 架构已用脚手架绕开归纳弱项。若重启：需 ≥12–24G 卡 + 更多蒸馏数据 + 少 epoch 防过拟合；否则性价比低于 VAD/热词。
- **beam search（ASR）**：端侧多份 KV cache 亏内存/易 OOM，提升小，不做。
- **确定性数字打捞 `must_cover`**：证伪（去噪配对实验反伤召回 −5pp），已回退。规律：**碰生成的补召回都伤 4B；只有纯后处理的 `keyword_index` 有效**。
- **embedding 追阿里粗章档**：不行（embedding 擅细粒度语义漂移、不擅粗粒度议题归组），不硬追；20 章覆盖飞书/阿里边界已够。
- **SenseVoice ASR**：板端 RKNN 导出/算子出不了正确结果（官方工具复现），已弃 → Qwen3-ASR。
- **CAM++ embedding 的 RKNN 版**：完整聚类中 speaker 退化，用 CPU/Torch 版 3D-Speaker。

## 🔒 交接前必做（安全 / 归属，详见 HANDOFF）

- 清除板端 `llm_judge.py` 里已失效 MaaS key（`sk-8Rja…`），改走环境变量。
- 仓库从个人 GitHub 迁公司 GitLab；`feature/transcript-postprocess` 合并进 main。
