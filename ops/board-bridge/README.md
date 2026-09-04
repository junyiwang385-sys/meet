# board-bridge：GitHub 命令信箱（零下载）

本机（开发机）经 GitHub 给板端下命令、拿结果，不用本机直连内网。

```
本机(写命令 push) ──GitHub── 实验机(轮询pull→执行→push结果) ──ssh── 板端
```

## 实验机一次性准备

1. 切到分支并拉取：
   ```
   cd D:\Meeting_Agent_mainline
   git checkout feature/transcript-postprocess
   git pull
   ```
2. **板端免密**（实验机能连板端，这一步只需输一次板端密码）：
   ```
   ssh-copy-id linaro@10.10.22.36
   ```
   之后 `ssh linaro@10.10.22.36 "..."` 免密执行。轮询器是非交互的，**没有免密会卡住**，务必先做。

## 启动轮询器（实验机，留一个窗口开着）

```
cd D:\Meeting_Agent_mainline
python ops\board-bridge\bridge_poll.py
```

看到 `轮询器启动` 就好了。它每 20 秒 `git pull` 一次，发现新命令就执行、把结果 push 回来。

## 工作方式

- 开发机在 `commands/` 放命令文件 `NNNN_说明.txt`（内容是一条在实验机上跑的命令行）
- 轮询器执行后在 `results/NNNN_说明.out` 写回 stdout/stderr/exit code 并 push
- 已有 `.out` 的命令不会重复执行

## 停止

轮询器窗口按 Ctrl+C。
