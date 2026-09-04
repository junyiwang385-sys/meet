@echo off
cd /d D:\Meeting_Agent_mainline
echo === 杀掉旧 Gateway(错settings) ===
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*meeting_agent_gateway_v0*' } | ForEach-Object { Write-Output ('kill gw pid ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }; Start-Sleep 2; Start-Process cmd -ArgumentList '/k','D:\Meeting_Agent_mainline\ops\board-bridge\run\start_gateway.bat'"
echo === Gateway 已用 agent1 settings 重启(新窗口) ===
