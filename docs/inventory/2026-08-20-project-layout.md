# Meeting Agent 项目目录说明

> 日期：2026-08-20  
> 根目录：`D:\Meeting_Agent_fresh`  
> 原则：源码、部署快照、生成物和历史归档分离；不因整理目录改变已验证算法或板端运行路径。

## 一、顶层目录

| 路径 | 定位 | 是否为当前源码 | 使用规则 |
|---|---|---:|---|
| `frontend/meeting-agent-ui-v1/` | React + TypeScript 正式前端 | 是 | 保持独立 Vite 工程；`node_modules/`、`dist/` 为可再生内容 |
| `scripts/board/` | RK1828 板端源码与验证入口 | 是 | 保留存在同目录导入关系的脚本位置 |
| `scripts/pc/` | PC Gateway 和 PC 端原型 | 是 | 只保留源码与必要静态资源，日志和测试音频进入 `output/` |
| `scripts/` 顶层 | Board、PC、ASR 和验证工具 | 是 | 模型转换和 LoRA 工具已移入 `archive/legacy/experiments/model-conversion/` |
| `board_sync_20260820/` | 2026-08-20 板端 `/userdata/meeting_agent/scripts` 快照 | 否，属于部署快照 | 只读保存；不在原地清理、重构或作为本地源码直接修改 |
| `docs/` | 架构、部署、验证、官方参考和目录清单 | 是 | 按文档职责选择权威来源 |
| `prompts/` | 当前 Prompt 资产 | 是 | 与使用它们的 validator/schema 保持版本一致 |
| `schemas/` | 会议转写和纪要 JSON Schema | 是 | 用于测试和接口约束 |
| `tests/` | 可重复测试与 fixtures | 是 | 不放板端一次性探针结果 |
| `data/` | 小型训练、校准和测试数据 | 部分 | 大模型、音频和生成数组不入 Git |
| `output/` | 本地日志、探针音频、构建与运行结果 | 否 | 已由 `.gitignore` 忽略，可再生成 |
| `archive/legacy/` | 旧 SDK、SenseVoice、历史实验和不兼容 Prompt | 否 | 只追溯，不作为当前实现依据 |
| `manifests/` | 部署快照和资产校验清单 | 是 | 用 SHA-256 检查同步内容是否被改写 |

## 二、三端职责

```text
Windows
  frontend/meeting-agent-ui-v1
  scripts/pc/meeting_agent_gateway_v0.py
  本地会议库与正式导出能力（继续开发）

RK1828
  scripts/board/board_agent_api_v0.py
  scripts/board/board_harness_worker_v0.py
  板端部署快照 board_sync_20260820/scripts

实验机
  archive/legacy/experiments/model-conversion/ 历史模型转换工具
  外部 rknn3-model-zoo / rknn3-toolkit / 原始模型
```

模型、原生 runtime 和实验机 SDK 不在当前源码仓库中。源码完整不等于可独立复现板端运行环境。

## 三、当前三条处理链路

### 1. 板端已部署 Harness 链路

来源：`board_sync_20260820/scripts/`

```text
board_agent_api_v0.py
  → board_harness_worker_v0.py
  → python3 -m harness.main
  → board_3dspeaker_segment_prepare_absorb_unknown.py
  → board_segment_asr_batch.py
  → harness/product_summary.py
  → meeting_result.json
```

该链路当前使用 3D-Speaker CPU/Torch、Qwen3-ASR Batch 和 Qwen3-4B v104 16K。快照暂不提升为本地正式源码，以避免同时维护两份 Harness。

### 2. CAM++ + Qwen3-ASR Batch 已验证基线

当前仓库已收录：

```text
scripts/board/asr/meeting_spk_asr_v1.py
scripts/board/asr/meeting_spk_asr_batch_v1.py
```

其中 Batch 文件直接导入同目录的 one-shot 文件，二者不可分开移动。此前板端使用过：

```text
run_spk_diarization.py
postprocess_unknown_boundary.py
run_short_window_sweep.py
```

截至本次整理，这三个 CAM++ 脚本尚未在 Windows 项目目录中定位到，因此没有创建占位文件，也没有把 CAM++ 链路误标成当前 Harness 的正式实现。找到真实导出后，应先检查依赖，再统一放入 `scripts/board/diarization/campp/`。

### 3. Windows 产品链路

```text
React 前端
  → PC Gateway
  → Board Agent
  → 板端 Harness
  → 前端核对和导出
```

目前前端第一阶段和 Gateway/Board Agent 通信链路已经有实现；会议核对、正式确认、导出、SQLite 会议库和录音能力仍需继续开发。

## 四、不可随意移动的文件

| 文件 | 原因 |
|---|---|
| `scripts/board/asr/meeting_spk_asr_batch_v1.py` | 直接 `import meeting_spk_asr_v1 as stable` |
| `scripts/board/asr/meeting_spk_asr_v1.py` | 为 Batch 提供切片、输出和公共工具 |
| `scripts/board/board_agent_api_v0.py` | 直接导入同目录的 Worker |
| `scripts/board/board_harness_worker_v0.py` | Board Agent 的 Harness 执行入口 |
| `scripts/` 顶层转换脚本（2026-08-20 记录） | 该日仍位于顶层；当前已归档到 `archive/legacy/experiments/model-conversion/` |
| `board_sync_20260820/scripts/` | 原始板端部署快照，需要保持可追溯性；新副本见 `snapshots/board_sync_20260820/` |

## 五、生成物处理

`harness_probe_sample.wav` 已从 `scripts/pc/` 移至：

```text
output/pc-gateway-probe/harness_probe_sample.wav
```

Gateway 日志已复制到：

```text
output/pc-gateway-probe/meeting_agent_gateway_v0.log
output/pc-gateway-probe/meeting_agent_gateway_v0.err.log
```

原日志仍位于 `scripts/pc/`，因为 Windows 返回 `Device or resource busy`，说明文件仍被运行中的进程占用。本次未终止进程；服务停止后再移动原日志即可。

## 六、快照校验

板端快照中 46 个非 `.pyc` 文件已记录 SHA-256：

```text
manifests/board-sync-20260820.sha256
```

校验清单覆盖正式运行文件、测试工具、patch 和历史备份；`__pycache__/*.pyc` 是可再生缓存，不计入清单，但仍保留在原始快照中。

## 七、后续目录操作边界

1. 将 Harness 从快照提升到 `scripts/board/` 前，先完成源码差异、动态导入和板端回归验证。
2. 将 CAM++ 脚本加入仓库前，先确认真实导出文件、ONNX 模型路径、Python 环境和输出格式。
3. 不在目录整理任务中删除模型、音频、测试结果、历史脚本或快照备份。
4. Git 提交应单独进行，避免把目录整理、算法修改和前端功能混为一个提交。
