# RK1828 / RKNN3 1.0.4：会议 Agent 部署测试记录

> **历史部署记录。** 本文保留 RKNN3 升级、模型准备、传输、板端命令和性能证据。文中的“当前”、机器路径和操作状态只代表对应记录时间，可能已被后续实现替代。现行入口见 [项目 README](../README.md)，运行机制见 [架构说明](architecture.md)。

本文档记录 RK1828 板端各阶段已经完成的部署测试：runtime 升级、模型准备、跨机器传输、板端测试命令、关键路径，以及过程中遇到的主要问题。

> **当前主线：** 运行时固定使用 `sliding_chapter_windows`，本地 Qwen 默认使用 4096-token 输出预算，不再使用一次性全量总结。ASR、canonical Timeline 和 RTTM/segment 后处理沿用现有链路不变。固定滑动窗口主线已在 30 个样本上完成板端验证，其中包括前 10 组和后 20 组复用既有 ASR 结果的运行。

## 1. 2026-08-12 历史部署结论

- 板端 RKNN3 runtime 已从 `1.0.0` 升级到 `1.0.4`，并验证成功。
- SenseVoiceSmall 在当前链路下仍不稳定，暂时不继续使用。
- Qwen3-ASR-0.6B 已在板端跑通：offline、online、online `-s` 流式刷新均正常。
- Qwen LLM 建议使用板端自带 `/usr/bin/rkllm3-server`，不要额外编译 C++ runner。
- 当前正式链路：

```text
完整 FLAC
-> CPU/Torch 3D-Speaker + unknown gap 吸收
-> Qwen3-ASR 常驻 Batch runner
-> canonical Timeline
-> Qwen3-4B ctx16k / rkllm3-server
-> JSON validation
-> 会议纪要
```

- Qwen3-4B ctx16k 在本次历史记录中完成未截断的完整会议 LLM 请求验证；当时的 `meeting_summary.json` 与 validation 发布状态仍待核对，该次记录已由后续 30 个样本的主线验证结果补充。
- Qwen3-8B ctx16k 已完成转换和文件校验，但在 RK1828 的 8K/16K `MODEL_SETUP` 阶段均失败；当前不再继续，正式 LLM 保留 Qwen3-4B ctx16k。

## 1.1 当前路径与同步速查

```text
Windows：D:\project\Meeting_Agent
WSL：   /root/Developer/Meeting_Agent
板端：  /userdata/meeting_agent
SSH：   linaro@<board-host>
Harness：/userdata/meeting_agent/scripts/harness
```

Windows 到 WSL 的同步命令应登录 WSL 后执行，由 WSL 主动拉取：

```bash
scp '<windows-user>@<windows-host>:D:/project/Meeting_Agent/<source>' \
  /root/Developer/Meeting_Agent/scripts/<filename>
```

WSL 到板端统一使用 `rsync`，默认限制约 10 MB/s：

```bash
rsync -avh --progress --bwlimit=10m \
  <source> \
  linaro@<board-host>:/userdata/meeting_agent/<target>/
```

不要从 Windows 主动向独立 WSL 推送，也不要使用 `scp` 向板端传输模型和脚本。

## 1.2 Qwen3-4B ctx16k 完整 Harness 命令

Qwen3-4B 模型目录应只保留一套正式的四类文件：

```text
/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k/
├── *.rknn
├── *.weight
├── *.tokenizer.gguf
└── *.embed.bin
```

板端执行：

```bash
cd /userdata/meeting_agent/scripts

python3 -m harness.main \
  --source-audio /userdata/meeting_agent/data/audio/L_R004S06C01.flac \
  --model-dir /userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k \
  --ctx 16384 \
  --predict 4096 \
  --max-tokens 4096 \
  --input-safety-tokens 512 \
  --input-chars-per-token 1.3 \
  --chunk-overlap-segments 1 \
  --out-dir /userdata/meeting_agent/output/harness_qwen3_4b_ctx16k \
  --ready-timeout 300 \
  --request-timeout 1200 \
  --overwrite
```

上面的命令使用当前统一的 4K 输出预算。以下性能数据来自较早的 16K 完整请求历史基线，仅用于说明当时的模型和板端资源状态，不代表上述 4K 滑动窗口命令的最新性能结果。

已确认的历史数据：

```text
context_truncated: false
server return_code: 0
prompt / completion / total: 10821 / 1561 / 12382 tokens
remaining context: 4002 tokens
server ready / request: 21.043s / 46.949s
prefill / decode: 545.919 / 57.941 tokens/s
segmentation / Batch ASR: 249.443s / 72.594s
baseline / board peak / delta: 816.492 / 2680.770 / 1864.277 MB
minimum MemAvailable: 5233.578 MB
LLM phase board peak: 1273.535 MB
rkllm3-server HWM: 281.625 MB
```

查看最终状态：

```bash
python3 -m json.tool /userdata/meeting_agent/output/harness_qwen3_4b_ctx16k/stage_status.json
python3 -m json.tool /userdata/meeting_agent/output/harness_qwen3_4b_ctx16k/meeting_result.json
python3 -m json.tool /userdata/meeting_agent/output/harness_qwen3_4b_ctx16k/03_llm_summary/validation.json
```

只有 `meeting_result.json` 为 `status: ok`、最终 validation 通过、同批 `meeting_summary.json`、`meeting_frontend.json`、`meeting_display.txt` 和 `04_compat_export/manifest.json` 均存在，才能称为板端会议总结完整发布成功。`response.json`、usage 和 `context_truncated=false` 只能证明单次 LLM 请求成功且输入未截断。Harness 默认保留 thinking，将 `</think>` 后的 final JSON 单独校验；当前生产路径无论输入长度，都固定执行自然章节边界驱动的滑动窗口，随后生成全文摘要并复核待办。

---

以下章节包含早期 runtime 安装、单音频 demo、旧目录和旧传输方式的排查过程。当前操作优先采用上面的路径、`rsync` 和 Harness 命令。

## 2. 关键路径

### 2.1 WSL 端路径

项目目录：

```bash
/root/Developer/Meeting_Agent
```

模型目录：

```bash
/root/Developer/Meeting_Agent/Model
```

RKNN3 v1.0.4 SDK：

```bash
/root/Developer/Meeting_Agent/RKNN3_v1.0.4_sdk
/root/Developer/Meeting_Agent/RKNN3_v1.0.4_sdk/RK1820_RK1828_SODIMM
/root/Developer/Meeting_Agent/RKNN3_v1.0.4_sdk/rknn3-toolkit-1.0.4
```

Model Zoo v1.0.4：

```bash
/root/Developer/Meeting_Agent/Model/rknn3-model-zoo-v104
```

已准备模型目录：

```bash
/root/Developer/Meeting_Agent/Model/Qwen2.5-3B
/root/Developer/Meeting_Agent/Model/Qwen2.5-7B
/root/Developer/Meeting_Agent/Model/Qwen3-4B
/root/Developer/Meeting_Agent/Model/Qwen3-ASR-0.6B
```

GCC10 交叉编译工具链：

```bash
/root/Developer/toolchains/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu
```

Qwen3-ASR 编译输出目录：

```bash
/root/Developer/Meeting_Agent/Model/rknn3-model-zoo-v104/install/rk3588_linux_aarch64/rknn_Qwen3_ASR_demo
```

### 2.2 板端路径

Qwen3-ASR 统一后板端目录：

```bash
# ASR demo 可执行文件和 lib/
/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo

# ASR RKNN 模型文件
/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn

# 测试音频/会议录音
/userdata/meeting_agent/data/audio
```

板端 LLM 模型目录：

```bash
/userdata/meeting_agent/models/llm/v104/qwen2.5-7b-v104
/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104
```

runtime v1.0.4 安装包：

```bash
/userdata/rknn3_rk182x_sodimm_installer_arm64_v104.tgz
```

旧 runtime 备份：

```bash
/userdata/backup_rknn3_v100
```

---

## 3. RKNN3 runtime 升级到 1.0.4

### 3.1 WSL 端确认安装包

安装包位置：

```bash
cd /root/Developer/Meeting_Agent/RKNN3_v1.0.4_sdk/RK1820_RK1828_SODIMM
ls -lh
```

关键文件：

```bash
rknn3_rk182x_sodimm_installer_arm64.tgz
rknn3-rk182x-sodimm_1.0.401_arm64.deb
```

可通过解包后检查版本确认是 1.0.4：

```bash
mkdir -p /tmp/rknn3_v104_check

tar -xzf rknn3_rk182x_sodimm_installer_arm64.tgz \
  -C /tmp/rknn3_v104_check

strings /tmp/rknn3_v104_check/system_root/lib/librknn3_api.so \
  | grep -m1 "librknn3_api version"
```

### 3.2 上传到板端（历史安装记录）

下面的 `scp` 命令保留为当时 runtime 安装过程记录。当前 WSL 到板端传输统一使用本文开头的 `rsync --bwlimit=10m`。

WSL 端：

```bash
scp -O \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=120 \
  -o TCPKeepAlive=yes \
  /root/Developer/Meeting_Agent/RKNN3_v1.0.4_sdk/RK1820_RK1828_SODIMM/rknn3_rk182x_sodimm_installer_arm64.tgz \
  linaro@<board-host>:/home/linaro/rknn3_rk182x_sodimm_installer_arm64_v104.tgz
```

板端：

```bash
sudo mv /home/linaro/rknn3_rk182x_sodimm_installer_arm64_v104.tgz /userdata/
sha256sum /userdata/rknn3_rk182x_sodimm_installer_arm64_v104.tgz
```

### 3.3 板端安装

```bash
cd /tmp
rm -rf rknn3_v104_install
mkdir -p rknn3_v104_install

sudo tar -xzf /userdata/rknn3_rk182x_sodimm_installer_arm64_v104.tgz \
  -C /tmp/rknn3_v104_install

cd /tmp/rknn3_v104_install
ls -lh
sudo ./install.sh
```

如果包内脚本名不是 `install.sh`，以实际 `ls` 看到的安装脚本为准。

### 3.4 验证版本

```bash
strings /usr/lib/librknn3_api.so | grep -m1 "librknn3_api version"
sudo systemctl status rknn3.service --no-pager
```

已验证结果：

```text
librknn3_api version: 1.0.4
rknn3.service active (running)
```

---

## 4. 模型转换和模型准备

### 4.1 Qwen LLM 模型

Qwen2.5/Qwen3 LLM 运行需要四类文件：

```text
.rknn / .weight / .tokenizer.gguf / .embed.bin
```

本项目转换脚本主要是：

```bash
scripts/convert_qwen3_v100_ctx.sh
scripts/export_qwen3_llm_v100.py
scripts/export_qwen3_rknn_v100_ctx.py
```

虽然脚本名里带 `v100`，但可以通过 `PYTHON=...` 指定 RKNN3 toolkit 1.0.4 环境。

示例：

```bash
cd /root/Developer/Meeting_Agent

PYTHON=/root/Developer/test/miniconda3/envs/rknn_v104_test/bin/python \
  bash scripts/convert_qwen3_v100_ctx.sh \
  /path/to/hf_model \
  /root/Developer/Meeting_Agent/Model/Qwen3-4B \
  8192
```

本轮板端实际测试到的 LLM 模型目录，统一后存放在：

```bash
/userdata/meeting_agent/models/llm/v104/qwen2.5-7b-v104
/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104
```

### 4.2 Qwen3-ASR 模型

Qwen3-ASR 使用已经转换好的目录：

```bash
/root/Developer/Meeting_Agent/Model/Qwen3-ASR-0.6B
```

Qwen3-ASR 不能用 SenseVoice runner，需要使用 RKNN3 Model Zoo v1.0.4 里的官方 demo：

```bash
/root/Developer/Meeting_Agent/Model/rknn3-model-zoo-v104/examples/Qwen3_ASR
```

---

## 5. Qwen3-ASR runner 编译

旧的 `rknn3-model-zoo` 是 `V1.0.0`，没有 Qwen3-ASR 示例，所以使用 v1.0.4：

```bash
/root/Developer/Meeting_Agent/Model/rknn3-model-zoo-v104
```

编译命令：

```bash
cd /root/Developer/Meeting_Agent/Model/rknn3-model-zoo-v104

export GCC_COMPILER=/root/Developer/toolchains/gcc-arm-10.3-2021.07-x86_64-aarch64-none-linux-gnu/bin/aarch64-none-linux-gnu

./build-linux.sh -t rk3588 -a aarch64 -d Qwen3_ASR -b Release
```

输出目录：

```bash
install/rk3588_linux_aarch64/rknn_Qwen3_ASR_demo
```

注意：必须使用 GCC10.3 工具链。之前用 apt 的 GCC13 编译后，板端运行会报 `GLIBC_2.38` / `GLIBCXX_3.4.32` 不存在。

---

## 6. 打包并从 WSL 传到板端（历史单音频 demo 记录）

本节保留早期 `/userdata/v104_test` 与 `scp` 流程用于追溯。当前正式目录是 `/userdata/meeting_agent/`，当前传输方式是 `rsync --bwlimit=10m`。

### 6.1 WSL 端打包

```bash
cd /root/Developer/Meeting_Agent/Model/rknn3-model-zoo-v104

mkdir -p install/rk3588_linux_aarch64/rknn_Qwen3_ASR_demo/model

cp -a /root/Developer/Meeting_Agent/Model/Qwen3-ASR-0.6B/* \
  install/rk3588_linux_aarch64/rknn_Qwen3_ASR_demo/model/

cd install/rk3588_linux_aarch64

tar -czf /root/Developer/Meeting_Agent/Model/qwen3_asr_demo_board_gcc10.tar.gz \
  rknn_Qwen3_ASR_demo
```

### 6.2 板端准备目录权限

```bash
sudo mkdir -p /userdata/v104_test
sudo chown -R linaro:linaro /userdata/v104_test
```

### 6.3 WSL 端传输

```bash
scp -O \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=120 \
  -o TCPKeepAlive=yes \
  -o Compression=no \
  -l 20000 \
  /root/Developer/Meeting_Agent/Model/qwen3_asr_demo_board_gcc10.tar.gz \
  linaro@<board-host>:/userdata/v104_test/
```

说明：大模型包建议传到 `/userdata`，不要传到 `/home/linaro` 所在的 `/` 分区；之前 `/` 分区空间不够且 scp 容易中断。

---

## 7. 板端测试 Qwen3-ASR

### 7.1 解包

```bash
cd /userdata/v104_test

rm -rf qwen3_asr_gcc10
mkdir -p qwen3_asr_gcc10

tar -xzf qwen3_asr_demo_board_gcc10.tar.gz -C qwen3_asr_gcc10

cd qwen3_asr_gcc10/rknn_Qwen3_ASR_demo
export LD_LIBRARY_PATH=./lib
```

### 7.2 Offline 测试

```bash
./rknn_qwen3_asr_demo \
  model/encoder.rknn \
  model/encoder.weight \
  model/llm.rknn \
  model/llm.weight \
  model/llm.tokenizer.gguf \
  model/llm.embed.bin \
  0xff \
  0xff \
  asr_en.wav
```

已验证：offline 正常输出英文转写，RTF 约 `0.03x`，速度远快于实时。

### 7.3 Online 测试

```bash
./rknn_qwen3_asr_demo_online \
  model/encoder_online.rknn \
  model/encoder_online.weight \
  model/llm.rknn \
  model/llm.weight \
  model/llm.tokenizer.gguf \
  model/llm.embed.bin \
  0xff \
  0xff \
  asr_en.wav
```

已验证：online 正常输出最终转写结果。

### 7.4 Online 流式刷新测试

```bash
./rknn_qwen3_asr_demo_online \
  model/encoder_online.rknn \
  model/encoder_online.weight \
  model/llm.rknn \
  model/llm.weight \
  model/llm.tokenizer.gguf \
  model/llm.embed.bin \
  0xff \
  0xff \
  asr_en.wav \
  -s
```

已验证：`-s` 模式正常。该模式会反复刷新中间结果，终端日志复制出来可能看起来重复，最终结果以 `Final Commit Result` 为准。

---

## 8. 板端测试 Qwen LLM

LLM 使用板端自带服务：

```bash
/usr/bin/rkllm3-server
```

它不是 WSL 编译出来的 runner，所以不受 GCC13/GCC10 的 glibc 版本问题影响。

### 8.1 测 Qwen3-4B

终端 1：

```bash
cd /userdata/meeting_agent/models/llm/v104/qwen3-4b-v104

/usr/bin/rkllm3-server \
  -m qwen3_4b_lifelog_real_merged-ctx8192.rknn \
  --weight qwen3_4b_lifelog_real_merged-ctx8192.weight \
  --vocab qwen3_4b_lifelog_real_merged.tokenizer.gguf \
  --embed qwen3_4b_lifelog_real_merged.embed.bin \
  -c 4096 \
  -n 128 \
  --host 127.0.0.1 \
  --port 18201
```

终端 2：

```bash
curl -s http://127.0.0.1:18201/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages":[{"role":"user","content":"请用中文简短回答：你能帮助整理会议纪要吗？回答两句话。"}],
    "max_tokens":96,
    "temperature":0.1
  }'
```

关闭：

```bash
pkill -f "rkllm3-server.*18201"
```

### 8.2 测 Qwen2.5-7B

终端 1：

```bash
cd /userdata/meeting_agent/models/llm/v104/qwen2.5-7b-v104

/usr/bin/rkllm3-server \
  -m Qwen2.5-7B-Instruct-ctx8192-v100-eager-int4.rknn \
  --weight Qwen2.5-7B-Instruct-ctx8192-v100-eager-int4.weight \
  --vocab Qwen2.5-7B-Instruct.tokenizer.gguf \
  --embed Qwen2.5-7B-Instruct.embed.bin \
  -c 4096 \
  -n 128 \
  --host 127.0.0.1 \
  --port 18202
```

终端 2：

```bash
curl -s http://127.0.0.1:18202/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages":[{"role":"user","content":"请用中文简短回答：你能帮助整理会议纪要吗？回答两句话。"}],
    "max_tokens":96,
    "temperature":0.1
  }'
```

关闭：

```bash
pkill -f "rkllm3-server.*18202"
```

---

## 9. 中间遇到的问题

### 9.1 SenseVoice 输出异常

SenseVoiceSmall 在 runtime 1.0.0 和 1.0.4 下都没有得到可信输出，表现包括空结果、全 blank 或乱码。因此当前不继续使用 SenseVoice，改用 Qwen3-ASR。

### 9.2 Qwen3-ASR 需要官方专用 runner

Qwen3-ASR 不是普通 CTC ASR 模型，包含 encoder 和 LLM 两部分，不能使用 SenseVoice runner。必须使用 Model Zoo v1.0.4 的 `examples/Qwen3_ASR`。

### 9.3 编译缺头文件/库

编译时缺过 `rknn3_api.h`、`float16.h` 和 arm64 版本 `librknn3_api.so`。解决方式：

- 头文件来自：`/root/Developer/1828/tmp/rknn3_include`
- arm64 库从 RKNN3 v1.0.4 SODIMM installer 解出
- 放入 Model Zoo 的 `3rdparty/rknpu3` 对应目录

### 9.4 GCC13 编译产物板端不兼容

apt GCC13 编译出的 ASR runner 依赖 `GLIBC_2.38` / `GLIBCXX_3.4.32`，板端只有 `GLIBC_2.36` / `GLIBCXX_3.4.30`。解决方式是使用 ARM GNU 10.3 重新编译。

### 9.5 FFTW non-PIC 链接问题

Qwen3-ASR 编译时遇到 bundled `libfftw3f.a` non-PIC 链接错误，解决方式是在 Qwen3_ASR 的 CMake target 上加 `-no-pie`。

### 9.6 历史 scp 权限和空间问题

- 早期直接传 `/userdata` 可能权限不足，需要先 `chown` 测试目录；
- `/home/linaro` 所在 `/` 分区空间不够，不适合放大模型包；
- 当前已统一改为向 `/userdata/meeting_agent/` 使用 `rsync --bwlimit=10m`，不再使用 scp 向板端传输。

### 9.7 多 RKNN 设备 warning

运行时提示发现多个 RKNN 设备但未指定 device id，默认使用 PCIe 设备 `0003:31:00.0`。本轮测试在默认设备上已成功，该 warning 不影响当前验证结果。

---

## 10. 清理建议

路径统一后，旧的 `/userdata/v104_test` 只应保留尚未迁移的临时包；当前主线 ASR runtime / model / audio 已迁移到：

```bash
/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo
/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn
/userdata/meeting_agent/data/audio/asr_en.wav
```

如果确认 `/userdata/v104_test` 里没有其他需要保留的内容，可以删除旧空目录或旧临时包；优先使用 `rmdir` 删除空目录，避免误删。

WSL 端可以删除旧 tar 和临时打包目录，但建议保留源模型、v1.0.4 SDK、Model Zoo v1.0.4 和 GCC10 工具链。

---

## 11. 最终部署建议

部署时建议分成两个部分：

```text
ASR：Qwen3-ASR runner
LLM：/usr/bin/rkllm3-server
```

ASR：

```bash
/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo/rknn_qwen3_asr_demo
/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo/rknn_qwen3_asr_demo_online
/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn
```

LLM：

```bash
/usr/bin/rkllm3-server
```

后续如果是会议录音文件，优先用 offline；如果是实时语音识别，用 online 或 online `-s`。

---

## 12. 一键链路和内存峰值测试

当前新增板端脚本：

```bash
scripts/board_meeting_chain_profile.py
```

用途：一键执行 Qwen3-ASR 转写、transcript 整理、启动 `rkllm3-server` 生成会议纪要 JSON，并通过 `/proc/meminfo` 和 `/proc/<pid>/status` 记录板端整体内存与 ASR / LLM 进程内存峰值。

统一后的板端目录建议：

```text
/userdata/meeting_agent/
├── scripts/                 自研 Python/Shell 脚本
├── runtime/asr/             Qwen3-ASR 官方 demo 可执行文件和 lib/
├── models/asr/              Qwen3-ASR RKNN 模型文件
├── models/llm/              rkllm3-server 使用的 LLM 模型目录
├── data/audio/              测试音频和会议录音输入
├── data/transcripts/        可选 transcript 输入/中间文本
├── data/prompts/            可选 prompt 模板
├── output/e2e/              ASR -> LLM 全链路输出
├── output/asr/              ASR 单测输出
├── output/llm/              LLM 单测输出
└── output/memory/           内存压测输出
```

当前正式 Batch ASR runtime（由 Harness 调用）：

```text
ASR batch runtime：/userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo
ASR executable：rknn_qwen3_asr_batch_demo
ASR model：/userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn
输入：mono / 16 kHz / 16-bit PCM seg_*.wav
Python wrapper：/userdata/meeting_agent/scripts/board_segment_asr_batch.py
当前完整会议 LLM：/userdata/meeting_agent/models/llm/v104/qwen3-4b-v104-ctx16k
LLM server：/usr/bin/rkllm3-server
```

板端运行示例：

```bash
python3 /userdata/meeting_agent/scripts/board_segment_asr_batch.py \
  --wav-dir /userdata/meeting_agent/output/segment_prepare_cpu_absorb_unknown_2s/cut_audio/wav_segments \
  --manifest /userdata/meeting_agent/output/segment_prepare_cpu_absorb_unknown_2s/cut_audio/cut_segments.csv \
  --asr-dir /userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_batch_demo \
  --asr-model-dir /userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn \
  --out-dir /userdata/meeting_agent/output/segment_asr_cpu_absorb_unknown_2s_batch \
  --overwrite
```

wrapper 会检查 WAV 格式，自动生成无表头的 `job_id<TAB>wav_path` runner manifest。`cut_segments.csv` 只用于保留 start/end/speaker 元数据。旧 `rknn_Qwen3_ASR_demo` 相关内容保留为早期单音频 smoke 和编译记录，不再作为会议 segment ASR 的正式路径。

查看结果：

```bash
python3 -m json.tool /userdata/meeting_agent/output/e2e/asr_en_default/chain_summary.json
python3 -m json.tool /userdata/meeting_agent/output/e2e/asr_en_default/memory_summary.json
python3 -m json.tool /userdata/meeting_agent/output/e2e/asr_en_default/summary.json
```

关键输出文件：

```text
asr_raw.log                  ASR 原始日志
transcript_normalized.txt    送入 LLM 的转写文本
rkllm_server.log             LLM server 日志
summary.json                 解析成功后的会议纪要 JSON
chain_summary.json           全链路状态、耗时、usage/timings、输出索引
memory_summary.json          板端整体和 ASR/LLM 进程内存峰值
memory_samples.jsonl         内存采样时间线
```

如果测试 Qwen3-4B lifelog 模型：

```bash
python3 /userdata/meeting_agent/scripts/board_meeting_chain_profile.py \
  --asr-dir /userdata/meeting_agent/runtime/asr/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo \
  --asr-model-dir /userdata/meeting_agent/models/asr/qwen3-asr-0.6b-rknn \
  --audio /userdata/meeting_agent/data/audio/test_meeting.wav \
  --model-dir /userdata/meeting_agent/models/llm/v104/qwen3-4b-v104 \
  --ctx 4096 \
  --predict 1024 \
  --max-tokens 1024 \
  --out-dir /userdata/meeting_agent/output/e2e/qwen3_4b_test \
  --overwrite
```
