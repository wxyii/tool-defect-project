@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%.mvn\wrapper\maven-wrapper.ps1" %*
exit /b %ERRORLEVEL%
