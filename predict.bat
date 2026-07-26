@echo off
REM Tool Defect Inference Runner
REM Usage: predict.bat <task> <input> <output>

setlocal EnableDelayedExpansion

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERROR] Python not found: %PYTHON%
    exit /b 1
)

set "PYTHONPATH=%PROJECT_ROOT%\src"

if "%~1"=="" goto usage
if "%~2"=="" goto usage
if "%~3"=="" goto usage

set "TASK=%~1"
set "INPUT=%~2"
set "OUTPUT=%~3"

set "INPUT_PATH=%PROJECT_ROOT%\%INPUT%"
set "OUTPUT_PATH=%PROJECT_ROOT%\%OUTPUT%"
set "CONFIG_PATH=%PROJECT_ROOT%\configs\default.json"

echo ========================================
echo  Tool Defect Inference
echo ========================================
echo  Task   : %TASK%
echo  Input  : %INPUT%
echo  Output : %OUTPUT%
echo ----------------------------------------

"%PYTHON%" -m tool_defect.cli predict --task %TASK% --input "%INPUT_PATH%" --output "%OUTPUT_PATH%" --config "%CONFIG_PATH%"

set "EXITCODE=%ERRORLEVEL%"

echo ----------------------------------------
if %EXITCODE%==0 (
    echo [OK] Inference complete!
    echo Output files:
    echo   - Visualizations: %OUTPUT_PATH%\visualizations\
    echo   - Masks         : %OUTPUT_PATH%\masks\
    echo   - Predictions   : %OUTPUT_PATH%\predictions.csv
) else (
    echo [FAIL] Exit code: %EXITCODE%
)

exit /b %EXITCODE%

:usage
echo Usage: predict.bat ^<task^> ^<input^> ^<output^>
echo.
echo Examples:
echo   predict.bat multitask data\images\unqualified\100.png outputs\result
echo   predict.bat multitask data\images\unqualified outputs\batch
echo   predict.bat classification data\images\qualified\100.png outputs\cls
exit /b 1
