@echo off
title MeetFrontend
cd /d D:\Meeting_Agent_mainline\frontend\meeting-agent-ui-v1
> .env.local echo VITE_API_MODE=gateway
>> .env.local echo VITE_GATEWAY_URL=http://127.0.0.1:8787
echo === 前端 real 模式,网关 http://127.0.0.1:8787 ===
call npm install
call npm run dev
echo === 前端已退出 ===
pause
