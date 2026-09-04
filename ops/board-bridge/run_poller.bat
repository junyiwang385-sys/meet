@echo off
title MeetBridgePoller
cd /d D:\Meeting_Agent_mainline
:loop
echo === [%date% %time%] 启动轮询器 ===
python ops\board-bridge\bridge_poll.py
echo === 轮询器退出(code=%errorlevel%)，5 秒后自动重启，Ctrl+C 可终止 ===
timeout /t 5 >nul
goto loop
