@echo off
title MeetFrontend
pushd "%~dp0..\..\frontend\meeting-agent-ui-v1"
> .env.local echo VITE_API_MODE=gateway
>> .env.local echo VITE_GATEWAY_URL=http://127.0.0.1:8787
if not exist node_modules (
  echo [Frontend] first run: installing dependencies ^(npm install^) ...
  call npm install
)
echo [Frontend] npm run dev  ^(Vite :5173 -^> Gateway :8787^)
call npm run dev
echo.
echo [Frontend] process exited. Close this window to free port 5173.
popd
pause
