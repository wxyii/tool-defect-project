#Requires -Version 5.1
<#
.SYNOPSIS
    Run tool-defect inference with the project virtual environment.
.EXAMPLE
    .\predict.ps1 -Task multitask -Input data\images\unqualified\100.png -Output outputs\result
.EXAMPLE
    .\predict.ps1 -Task classification -Input data\images\qualified -Output outputs\batch
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("classification", "multitask")]
    [string]$Task,

    [Parameter(Mandatory = $true)]
    [Alias("Input")]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$Output,

    [string]$ModelDir,

    [string]$Config = "configs\default.json"
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Error "Virtual-environment Python was not found: $PythonExe"
    Write-Host "Create .venv and install requirements.txt first." -ForegroundColor Yellow
    exit 1
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"

$Arguments = @(
    "-m", "tool_defect.cli",
    "predict",
    "--task", $Task,
    "--input", (Join-Path $ProjectRoot $InputPath),
    "--output", (Join-Path $ProjectRoot $Output),
    "--config", (Join-Path $ProjectRoot $Config)
)

if ($ModelDir) {
    $Arguments += "--model-dir"
    $Arguments += Join-Path $ProjectRoot $ModelDir
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Tool Defect Inference" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Task       : $Task"
Write-Host "Input      : $InputPath"
Write-Host "Output     : $Output"
Write-Host "PYTHONPATH : $env:PYTHONPATH" -ForegroundColor DarkGray
Write-Host "----------------------------------------" -ForegroundColor Cyan

& $PythonExe @Arguments
$ExitCode = $LASTEXITCODE

Write-Host "----------------------------------------" -ForegroundColor Cyan
if ($ExitCode -eq 0) {
    $OutputFullPath = Join-Path $ProjectRoot $Output
    Write-Host "Inference completed." -ForegroundColor Green
    Write-Host "Predictions    : $OutputFullPath\predictions.csv"
    Write-Host "Masks          : $OutputFullPath\masks\"
    Write-Host "Visualizations : $OutputFullPath\visualizations\"
} else {
    Write-Host "Inference failed with exit code $ExitCode." -ForegroundColor Red
}

exit $ExitCode
