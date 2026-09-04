@echo off
title MeetGateway
cd /d D:\Meeting_Agent_mainline
set PYTHONPATH=src
echo === Gateway 启动: port 8787, settings=gateway_settings_agent1.json(board 18082) ===
python -m meeting_agent.adapters.gateway.meeting_agent_gateway_v0 --port 8787 --settings-path runtime\gateway_settings_agent1.json
echo === Gateway 已退出,窗口保留查看日志 ===
pause
