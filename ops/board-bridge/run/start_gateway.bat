@echo off
title MeetGateway
cd /d D:\Meeting_Agent_mainline
set PYTHONPATH=src
echo === Gateway 启动: port 8787, board=http://10.10.22.36:18082 ===
python -m meeting_agent.adapters.gateway.meeting_agent_gateway_v0 --port 8787 --board-url http://10.10.22.36:18082
echo === Gateway 已退出,窗口保留查看日志 ===
pause
