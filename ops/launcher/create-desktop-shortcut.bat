@echo off
chcp 65001 >nul
title Create desktop shortcut
rem Creates a Desktop shortcut "Meeting Agent Demo" pointing at start-demo.bat.
powershell -NoProfile -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Meeting Agent Demo.lnk'); $s.TargetPath='%~dp0start-demo.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,137'; $s.Description='Meeting Agent on-device demo (Gateway + frontend)'; $s.Save()"
if %errorlevel%==0 (echo [OK] Created desktop shortcut: "Meeting Agent Demo") else (echo [X] Failed to create shortcut)
pause
