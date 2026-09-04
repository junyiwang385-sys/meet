#!/usr/bin/env python3
"""GitHub 命令信箱轮询器（零下载，只用 git + 标准库）。

在【实验机】上运行，留一个窗口开着。它会：
  1. 每隔 N 秒 git pull
  2. 发现 commands/ 里有新命令文件（还没有对应 results/*.out）就执行
  3. 把 stdout/stderr/exit 写进 results/<同名>.out，git commit + push

命令文件是纯文本，内容就是一条在【实验机】上执行的命令行（Windows cmd.exe）。
要操作板端就写 `ssh linaro@10.10.22.36 "远程命令"`（需先做过一次免密，见 README）。

用法：  python ops/board-bridge/bridge_poll.py
停止：  Ctrl+C
"""

from __future__ import annotations

import datetime
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]        # 仓库根
BRIDGE = ROOT / "ops" / "board-bridge"
CMD_DIR = BRIDGE / "commands"
RES_DIR = BRIDGE / "results"
INTERVAL = 20                                       # 轮询间隔（秒）
CMD_TIMEOUT = 1800                                  # 单条命令超时（秒）


def run(args, timeout=None):
    return subprocess.run(
        args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=isinstance(args, str),
    )


def git(*a):
    return run(["git", *a])


def stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")


def process_one(cmd_file: Path) -> None:
    out_file = RES_DIR / (cmd_file.stem + ".out")
    command = cmd_file.read_text(encoding="utf-8").strip()
    print(f"[{stamp()}] 执行 {cmd_file.name}: {command[:80]}")
    started = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        r = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CMD_TIMEOUT,
            shell=True,
        )
        body = (
            f"# cmd file : {cmd_file.name}\n"
            f"# started  : {started}\n"
            f"# exit code: {r.returncode}\n\n"
            f"===== STDOUT =====\n{r.stdout}\n"
            f"===== STDERR =====\n{r.stderr}\n"
        )
    except subprocess.TimeoutExpired:
        body = f"# cmd file : {cmd_file.name}\n# started  : {started}\n# ERROR: 超时 {CMD_TIMEOUT}s\n"
    except Exception as exc:  # noqa: BLE001
        body = f"# cmd file : {cmd_file.name}\n# started  : {started}\n# ERROR: {exc!r}\n"

    out_file.write_text(body, encoding="utf-8")
    git("add", str(out_file.relative_to(ROOT)).replace("\\", "/"))
    git("commit", "-m", f"bridge: result {cmd_file.stem}")
    push = git("push")
    if push.returncode != 0:
        print(f"[{stamp()}] push 失败，下轮重试：{push.stderr.strip()[:120]}")


def main() -> None:
    RES_DIR.mkdir(parents=True, exist_ok=True)
    CMD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{stamp()}] 轮询器启动，仓库 {ROOT}，每 {INTERVAL}s 拉取一次。Ctrl+C 停止。")
    while True:
        pull = git("pull", "--rebase", "--autostash")
        if pull.returncode != 0:
            print(f"[{stamp()}] git pull 失败：{pull.stderr.strip()[:120]}")
        pending = sorted(
            p for p in CMD_DIR.glob("*.txt")
            if not (RES_DIR / (p.stem + ".out")).exists()
        )
        if pending:
            print(f"[{stamp()}] 发现 {len(pending)} 条待执行")
            for cmd_file in pending:
                process_one(cmd_file)
        else:
            print(f"[{stamp()}] 无新命令")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
