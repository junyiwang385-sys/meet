@echo off
title MeetGateway
rem repo root = this file dir \ ..\..
pushd "%~dp0..\.."
set PYTHONPATH=src
echo [Gateway] port 8787, settings=runtime\gateway_settings_agent1.json (board 10.10.22.36:18082)
echo [Gateway] cwd=%CD%
python -m meeting_agent.adapters.gateway.meeting_agent_gateway_v0 --port 8787 --settings-path runtime\gateway_settings_agent1.json
echo.
echo [Gateway] process exited. Window kept for logs. Close it to free port 8787.
popd
pause
