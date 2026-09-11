@echo off
chcp 65001 >nul
title Meeting Agent Demo Launcher
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
echo.
pause
