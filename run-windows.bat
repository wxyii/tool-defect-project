@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
if /I "%~1"=="--help" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\dev\run-windows.ps1" -Action help
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%tools\dev\run-windows.ps1" %*
)
exit /b %ERRORLEVEL%
