@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\dev\setup-windows.ps1" %*
exit /b %ERRORLEVEL%
