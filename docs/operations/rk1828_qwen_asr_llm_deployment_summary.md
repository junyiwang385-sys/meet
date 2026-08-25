# RK1828 / RKNN3 1.0.4：会议 Agent 部署测试记录

本文档记录目前已经完成的 RK1828 板端测试流程：runtime 升级、模型准备、WSL 到板端传输、板端测试命令、关键路径，以及过程中遇到的主要问题。

## 1. 当前结论

- 板端 RKNN3 runtime 已从 `1.0.0` 升级到 `1.0.4`，并验证成功。
- SenseVoiceSmall 在当前链路下仍不稳定，暂时不继续使用。
- Qwen3-ASR-0.6B 已在板端跑通：offline、online、online `-s` 流式刷新均正常。
- Qwen LLM 建议使用板端自带 `/usr/bin/rkllm3-server`，不要额外编译 C++ runner。
- 推荐最终链路：

```text
会议音频 -> Qwen3-ASR 转写 -> 主程序整理 transcript -> rkllm3-server 调 Qwen LLM -> 会议纪要
```

---

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

Qwen3-ASR 已验证可运行目录：

```bash
/userdata/v104_test/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo
```

板端 LLM 模型目录：

```bash
/userdata/qwen25-7b-ctx8k-v100
/userdata/qwen3-4b-lifelog-real-ctx8k
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

### 3.2 上传到板端

WSL 端：

```bash
scp -O \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=120 \
  -o TCPKeepAlive=yes \
  /root/Developer/Meeting_Agent/RKNN3_v1.0.4_sdk/RK1820_RK1828_SODIMM/rknn3_rk182x_sodimm_installer_arm64.tgz \
  linaro@10.10.22.32:/home/linaro/rknn3_rk182x_sodimm_installer_arm64_v104.tgz
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

> 历史路径说明：本节记录当时模型转换脚本位于 `scripts/` 顶层的部署过程。
> 这些脚本现已移入 `archive/legacy/experiments/model-conversion/`，以下命令仅用于历史追溯，不能直接视为当前入口。

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

本轮板端实际测试到的 LLM 模型目录：

```bash
/userdata/qwen25-7b-ctx8k-v100
/userdata/qwen3-4b-lifelog-real-ctx8k
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

## 6. 打包并从 WSL 传到板端

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
  linaro@10.10.22.32:/userdata/v104_test/
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
cd /userdata/qwen3-4b-lifelog-real-ctx8k

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
cd /userdata/qwen25-7b-ctx8k-v100

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

### 9.6 scp 权限和空间问题

- 直接传 `/userdata` 可能权限不足，需要先 `chown` 测试目录。
- `/home/linaro` 所在 `/` 分区空间不够，不适合放大模型包。
- 大包传输建议用 scp keepalive 和限速参数。

### 9.7 多 RKNN 设备 warning

运行时提示发现多个 RKNN 设备但未指定 device id，默认使用 PCIe 设备 `0003:31:00.0`。本轮测试在默认设备上已成功，该 warning 不影响当前验证结果。

---

## 10. 清理建议

可以删除旧的错误 ASR 测试包：

```bash
sudo rm -rf /userdata/v104_test/board_rknn3_all_tests
```

可以删除已经解包后的传输 tar：

```bash
rm -f /userdata/v104_test/qwen3_asr_demo_board_gcc10.tar.gz
```

不要删除当前已验证可用目录：

```bash
/userdata/v104_test/qwen3_asr_gcc10
```

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
/userdata/v104_test/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo/rknn_qwen3_asr_demo
/userdata/v104_test/qwen3_asr_gcc10/rknn_Qwen3_ASR_demo/rknn_qwen3_asr_demo_online
```

LLM：

```bash
/usr/bin/rkllm3-server
```

后续如果是会议录音文件，优先用 offline；如果是实时语音识别，用 online 或 online `-s`。
