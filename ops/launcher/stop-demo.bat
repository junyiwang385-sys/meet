@echo off
chcp 65001 >nul
title Stop Meeting Agent Demo
echo Stopping Gateway and frontend ...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*meeting_agent_gateway_v0*' } | ForEach-Object { Write-Host ('kill gateway pid ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -like '*vite*' } | ForEach-Object { Write-Host ('kill frontend pid ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Done. (If any MeetGateway / MeetFrontend window remains, close it manually.)
pause
