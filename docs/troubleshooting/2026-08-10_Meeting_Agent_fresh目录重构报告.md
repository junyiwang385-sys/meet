# Meeting_Agent_fresh 目录重构报告

> 日期：2026-08-10  
> 分支：`feature/chao/meeting-agent`  
> 范围：仓库目录整理、核心技术文档导入、历史内容归档与本地静态验证  
> 状态：未提交、未推送、未合并 `origin/pipeline`

## 一、目标与原则

本次重构将原本混杂的 RKNN3 v1.0.0 / SenseVoice 历史资料、模型工具、一次性实验、PC 原型和当前 RK1828 主线拆分为四类：

```text
当前板端主线
模型转换与 LoRA 工具
架构 / 部署 / 验证 / 官方参考文档
archive/legacy 历史归档
```

执行原则：

- 历史源码、Prompt 和文档先归档，不永久删除；
- 只清除可再生的 Python bytecode 缓存和空目录；
- 不更改 ASR / diarization / LLM 算法逻辑；
- 不合并已分叉的 `origin/pipeline`；
- 不提交、不推送，由用户先审阅工作树。

## 二、恢复点

外部恢复目录：

```text
D:\Meeting_Agent_fresh_cleanup_backup_20260810_155809
```

包含：

| 内容 | 用途 |
|---|---|
| `working-tree.tar.gz` | 重构前完整工作树快照 |
| `repository.bundle` | 完整 Git 历史和分支恢复 |
| `git-status.txt` / `working-tree.diff` / `index.diff` | 重构前状态和差异 |
| `active-source/` | 5 个当时未跟踪的当前源码/依赖 |
| `input-docs/` | 用户选择导入的 2 份核心技术文档 |
| `SHA256SUMS` | 恢复文件完整性清单 |

验证结果：Git bundle 完整；`SHA256SUMS` 中 9/9 条记录匹配。

## 三、主要迁移结果

### 1. 当前主线

| 类型 | 新路径 | 结果 |
|---|---|---|
| ASR one-shot 基线 | `scripts/board/asr/meeting_spk_asr_v1.py` | 与备份逐字一致 |
| ASR Batch | `scripts/board/asr/meeting_spk_asr_batch_v1.py` | 与备份逐字一致；仍同目录导入稳定模块 |
| 全链路 smoke | `scripts/board/smoke/rk1828_v104_meeting_chain_smoke.py` | 与备份逐字一致 |
| LLM smoke | `scripts/board/llm/rkllm_smoke_test.py` | 从原活动路径移动 |
| PC FunASR 原型 | `scripts/pc/funasr/` | 明确与板端 Qwen3-ASR 主线隔离 |

模型转换与 LoRA 工具保留在 `scripts/` 顶层，以避免破坏现有相对路径依赖。

### 2. 文档

| 分类 | 新位置 |
|---|---|
| 架构权威文档 | `docs/architecture/RK1828会议助手-技术方案与选型.md` |
| 部署权威文档 | `docs/deployment/rk1828_qwen_asr_llm_deployment_summary.md` |
| Batch 实测证据 | `docs/validation/2026-08-10_RK1828_Qwen3-ASR批处理优化方案与验证结果.md` |
| Rockchip 官方资料 | `docs/reference/rockchip/` |
| 文档导航 | `docs/README.md` |

架构文档已同步 2026-08-10 状态：Qwen3-ASR Batch worker 已完成；长会议纪要、Golden Set、术语纠错和完整编排器仍待实现。

三份 Rockchip PDF 在迁移过程中曾被本机 `TsdEncrypt` 文件过滤驱动自动包装为 `TSD-Header` 格式；已通过保留原始 inode 的硬链接方式恢复。最终文件与 Git HEAD 原件长度及 SHA256 完全一致：

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| `Rockchip_RK182X_Quick_Start_RKNN3_SDK_V1.0.0_CN.pdf` | 5,389,840 | `b594f7a8ac713bcfb503e8f37cf0011a1a725515238c7a81d6469f8c5f6af842` |
| `Rockchip_RK182X_ReleaseNote_RKNN3_SDK_V1.0.0_CN.pdf` | 588,108 | `4f0ef4e93d4536e2025c0e4ddfd8d550a41387c8036cf1ce61905e71520972e7` |
| `Rockchip_RKNPU3_ReleaseNote_RKNN3_SDK_V1.0.4_CN.pdf` | 796,970 | `d8ac1b6e23d205d59f162956afc3bdc12d09eb97f38ad927a2b905c639c6e369` |

### 3. 历史归档

归档到 `archive/legacy/`：

| 分类 | 数量 | 说明 |
|---|---:|---|
| 旧主文档 | 1 | RKNN3 v1.0.0 / SenseVoice 时代，归档副本已脱敏 |
| 旧 Prompt | 2 | 与当前紧凑 validator schema 不兼容 |
| SenseVoice 链路 | 5 | runner 3 个文件 + 导出/测试脚本 2 个 |
| 一次性板端测试 | 5 | 已完成的历史验证 |
| 早期实验 | 7 | 转换、数据集、LoRA 和模板实验 |
| 合计 | 20 | 均可通过外部备份恢复 |

详细原路径、新路径、SHA256 和原因见 `archive/legacy/MANIFEST.md`。

### 4. 删除项

仅永久清除：

- 各位置生成的 `__pycache__/*.pyc`；
- 空的 `schemas/`、旧 `scripts/archive/`、`scripts/experiments/` 和 `runners/sensevoice_stage1/` 目录。

没有删除归档源码、历史 Prompt、用户数据、官方 PDF、模型工具或 `.claude/settings.local.json`。

## 四、当前已验证产品状态

本次目录整理不重复改变已验证算法结论：

| 能力 | 结果 |
|---|---|
| CAM++ diarization baseline | 3s window / 0.68 threshold |
| bridge4 切片 | 184 segment → 31 ASR unit → 87 chunk |
| Qwen3-ASR Batch | 87/87 成功，与 one-shot 文本/speaker/时间戳完全一致 |
| 性能 | 587.771s → 65.966s，8.91× 加速，节省 88.8% |
| 状态隔离 | A→B / B→A 顺序测试和 resume 均通过 |
| NPU handoff | ASR 退出后 Qwen3-4B 18s 就绪，HTTP 200 |

## 五、安全处理

- 旧 `docs/mainDoc.md` 曾包含板端明文密码；活动文档已移除，归档副本已替换为占位符。
- 仓库活动文档只保留部署记录中的设备用户名/IP，不包含密码或私钥；这些地址不是认证凭据。
- Git 历史未改写，因此旧提交中若曾存在真实凭据，仍应在设备侧轮换。

## 六、验证范围

本轮执行：

- 恢复点 bundle / SHA256 校验；
- 移动文件 SHA256 对比；
- 当前 Python 入口语法、模块导入和 `--help` 静态回归；
- Markdown 相对链接和旧路径引用检查；
- 明文凭据搜索；
- Git 分支、状态、diff 范围检查。

板端 87-chunk Batch 和 ASR→LLM handoff 已在同日完成实机验证，本轮未因目录重构重复占用板端 NPU。

## 七、下一阶段

目录重构完成后，产品主线继续：

```text
固定 meeting_minutes_v0 schema
  → 制作 dev-001 安全会议 Golden Set
  → 增加一场有明确决策 / 负责人 / 期限的任务型会议
  → 测试 1600 / 2000 / 2400 / 2700 token 单段预算
  → 建立固定窗口 map-reduce 基线
  → 对比边界吸附方案
  → 最后接入完整离线编排器
```

当前安全会议适合作为开发集验证主题覆盖、术语、否定词、数字和 evidence，不应作为最终锁定测试集。
