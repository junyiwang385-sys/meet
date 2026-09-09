#!/usr/bin/env python3
"""GitHub 命令信箱轮询器（健壮版，零下载，只用 git + 标准库）。

在【实验机】上运行。每隔 N 秒 git pull，发现 commands/ 有新命令文件（还没有对应
results/*.out）就执行，把输出写回 results/<同名>.out，git commit + push。

健壮性设计：
  - 命令输出写【临时文件】而非管道 → start 出来的长驻子进程不会拖住轮询器；
  - 单命令超时用 taskkill /F /T 杀【整个进程树】，写超时结果后继续；
  - 每轮循环包 try/except → 单条命令异常不会让轮询器崩溃，自动继续下一轮；
  - stdin=DEVNULL → 命令不会卡在等待输入。
配套 run_poller.bat：python 整个退出（硬崩）时自动重启本脚本。

命令文件是纯文本，内容是一条在【实验机】上执行的命令行（Windows cmd.exe）。
操作板端写 `ssh linaro@10.10.22.36 "远程命令"`（需先做过板端免密）。
启动长驻服务（Gateway/前端）请用 PowerShell Start-Process，别用 start，见 run/*.bat 由 Start-Process 拉起。

用法：  python ops/board-bridge/bridge_poll.py   （或跑 run_poller.bat 带自动重启）
停止：  Ctrl+C
"""

from __future__ import annotations

import datetime
import subprocess
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]        # 仓库根
BRIDGE = ROOT / "ops" / "board-bridge"
CMD_DIR = BRIDGE / "commands"
RES_DIR = BRIDGE / "results"
INTERVAL = 20                                       # 轮询间隔（秒）
CMD_TIMEOUT = 1800                                  # 单命令超时（秒）
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def git(*a):
    return subprocess.run(
        ["git", *a],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def stamp() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def process_one(cmd_file: Path) -> None:
    out_file = RES_DIR / (cmd_file.stem + ".out")
    command = cmd_file.read_text(encoding="utf-8").strip()
    print(f"[{stamp()}] 执行 {cmd_file.name}: {command[:70]}")
    started = datetime.datetime.now().isoformat(timespec="seconds")
    tmp_path = Path(tempfile.gettempdir()) / f"bridge_{cmd_file.stem}.raw"
    status = ""
    try:
        with open(tmp_path, "w", encoding="utf-8", errors="replace") as sink:
            proc = subprocess.Popen(
                command,
                cwd=str(ROOT),
                shell=True,
                stdout=sink,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,          # 不等输入
                creationflags=_NEW_GROUP,
            )
            try:
                rc = proc.wait(timeout=CMD_TIMEOUT)
                status = f"exit code: {rc}"
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
                proc.wait()
                status = f"TIMEOUT >{CMD_TIMEOUT}s（已 taskkill 整个进程树）"
    except Exception as exc:  # noqa: BLE001
        status = f"ERROR: {exc!r}"

    body = tmp_path.read_text(encoding="utf-8", errors="replace") if tmp_path.exists() else ""
    out_file.write_text(
        f"# cmd file : {cmd_file.name}\n# started  : {started}\n# {status}\n\n{body}\n",
        encoding="utf-8",
    )
    try:
        tmp_path.unlink()
    except OSError:
        pass
    git("add", str(out_file.relative_to(ROOT)).replace("\\", "/"))
    git("commit", "-m", f"bridge: result {cmd_file.stem}")
    push = git("push")
    if push.returncode != 0:
        print(f"[{stamp()}] push 失败，下轮重试：{push.stderr.strip()[:120]}")


def self_heal() -> None:
    """pull 失败（多为 rebase/autostash 弹栈冲突留下 unmerged）时，清干净并硬对齐上游。

    会丢弃本机未推送的本地提交（只可能是 result *.out，重跑对应命令即可再生），
    换取轮询器永远能向前走、不再被 "have unmerged files" 卡死。
    """
    git("rebase", "--abort")
    git("merge", "--abort")
    git("stash", "clear")
    git("fetch", "origin")
    up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up.returncode == 0:
        upstream = up.stdout.strip()
        r = git("reset", "--hard", upstream)
        print(f"[{stamp()}] 自愈：reset --hard {upstream} rc={r.returncode}")
    else:
        print(f"[{stamp()}] 自愈失败：拿不到上游分支，人工介入")


def loop_once() -> None:
    pull = git("pull", "--rebase", "--autostash")
    if pull.returncode != 0:
        print(f"[{stamp()}] git pull 失败：{pull.stderr.strip()[:120]} —— 尝试自愈")
        self_heal()
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


def _keep_system_awake() -> None:
    """锁住系统电源:轮询器在跑期间不睡眠/不待机(显示器仍可息屏)。

    修复"实验机一息屏→睡眠→轮询器停/断网"。ES_SYSTEM_REQUIRED 阻止系统睡眠,
    不设 ES_DISPLAY_REQUIRED 所以屏幕照常关。仅 Windows 生效,其它平台静默跳过。
    """
    try:
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        print(f"[{stamp()}] 已锁系统不睡眠(息屏不影响运行)。")
    except Exception as exc:  # noqa: BLE001
        print(f"[{stamp()}] 保持唤醒设置失败(忽略):{exc!r}")


def main() -> None:
    RES_DIR.mkdir(parents=True, exist_ok=True)
    CMD_DIR.mkdir(parents=True, exist_ok=True)
    _keep_system_awake()
    print(f"[{stamp()}] 轮询器启动(健壮版)，仓库 {ROOT}，每 {INTERVAL}s 拉取。Ctrl+C 停止。")
    while True:
        try:
            loop_once()
        except KeyboardInterrupt:
            raise
        except Exception:  # noqa: BLE001
            print(f"[{stamp()}] 本轮异常，已捕获并继续：\n{traceback.format_exc()}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
