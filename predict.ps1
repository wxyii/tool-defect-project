#Requires -Version 5.1
<#
.SYNOPSIS
    Tool Defect Inference Runner - 一键执行车刀缺陷推理
.DESCRIPTION
    自动设置 PYTHONPATH 并执行推理任务，输出可视化叠加图。
    无需手动激活虚拟环境或设置环境变量。
.EXAMPLE
    .\predict.ps1 -Task multitask -Input data\images\unqualified\100.png -Output outputs\result
.EXAMPLE
    .\predict.ps1 -Task multitask -Input data\images\unqualified -Output outputs\batch
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("classification", "multitask")]
    [string]$Task,

    [Parameter(Mandatory=$true)]
    [string]$Input,

    [Parameter(Mandatory=$true)]
    [string]$Output,

    [string]$ModelDir,

    [string]$Config = "configs\default.json"
)

# 获取脚本所在目录（项目根目录）
$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) {
    $ProjectRoot = (Get-Location).Path
}

# Python 解释器路径（使用虚拟环境中的 Python）
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# 检查 Python 是否存在
if (-not (Test-Path $PythonExe)) {
    Write-Error "虚拟环境 Python 不存在: $PythonExe"
    Write-Host "请先创建虚拟环境并安装依赖。" -ForegroundColor Yellow
    exit 1
}

# 设置 PYTHONPATH（关键！让 Python 能找到 src 下的模块）
$SrcDir = Join-Path $ProjectRoot "src"
$env:PYTHONPATH = $SrcDir

# 构建推理命令参数
$Arguments = @(
    "-m", "tool_defect.cli",
    "predict",
    "--task", $Task,
    "--input", (Join-Path $ProjectRoot $Input),
    "--output", (Join-Path $ProjectRoot $Output),
    "--config", (Join-Path $ProjectRoot $Config)
)

if ($ModelDir) {
    $Arguments += "--model-dir"
    $Arguments += (Join-Path $ProjectRoot $ModelDir)
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  车刀缺陷推理任务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "任务类型 : $Task" -ForegroundColor White
Write-Host "输入路径 : $Input" -ForegroundColor White
Write-Host "输出目录 : $Output" -ForegroundColor White
Write-Host "PYTHONPATH: $env:PYTHONPATH" -ForegroundColor DarkGray
Write-Host "----------------------------------------" -ForegroundColor Cyan

# 执行推理
& $PythonExe @Arguments

$ExitCode = $LASTEXITCODE

Write-Host "----------------------------------------" -ForegroundColor Cyan

if ($ExitCode -eq 0) {
    Write-Host "推理完成！" -ForegroundColor Green
    Write-Host ""
    $OutputFullPath = Join-Path $ProjectRoot $Output
    Write-Host "输出文件位置:" -ForegroundColor Yellow
    Write-Host "  - 可视化叠加图: $OutputFullPath\visualizations\" -ForegroundColor White
    Write-Host "  - 二值掩码图  : $OutputFullPath\masks\" -ForegroundColor White
    Write-Host "  - 预测结果CSV : $OutputFullPath\predictions.csv" -ForegroundColor White
} else {
    Write-Host "推理失败，退出码: $ExitCode" -ForegroundColor Red
}

exit $ExitCode
