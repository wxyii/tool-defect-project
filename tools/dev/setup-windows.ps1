#Requires -Version 5.1
<#
.SYNOPSIS
    Configure the project for native Windows development.

.DESCRIPTION
    This script does not call Docker or WSL. It checks Python 3.11,
    Node.js 20.13.1, pnpm 10.34.5, and Java 25, then creates the
    isolated Python environments used by this repository.
#>

param(
    [switch]$InstallPrerequisites,
    [switch]$SkipFrontend,
    [switch]$SkipJava,
    [switch]$SkipEdgeEnvironment,
    [switch]$SkipInferenceEnvironment,
    [switch]$IncludeLegacyGui
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$NodeVersion = "20.13.1"
$PnpmVersion = "10.34.5"
$NodeHome = Join-Path $ProjectRoot ".build\toolchains\node-v$NodeVersion-win-x64"
$CorepackHome = Join-Path $ProjectRoot ".build\toolchains\corepack"
$PnpmHome = Join-Path $ProjectRoot ".build\toolchains\pnpm"
$NativeTempHome = Join-Path $ProjectRoot ".build\toolchains\tmp"
$NodeArchiveName = "node-v$NodeVersion-win-x64.zip"
$NodeArchiveUrl = "https://nodejs.org/dist/v$NodeVersion/$NodeArchiveName"
$NodeChecksumsUrl = "https://nodejs.org/dist/v$NodeVersion/SHASUMS256.txt"

function Stop-WithError {
    param([string]$Message)
    throw "[WINDOWS-SETUP-FAILED] $Message"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$Label = $FilePath
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "$Label failed with exit code $LASTEXITCODE."
    }
}

function Get-CommandPath {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Get-ToolVersion {
    param(
        [string]$Path,
        [string]$Argument,
        [string]$ExtraArgument = $null
    )
    if (-not $Path) { return "" }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($ExtraArgument) {
            $output = & $Path $Argument $ExtraArgument 2>&1 | Out-String
        } else {
            $output = & $Path $Argument 2>&1 | Out-String
        }
        return $output.Trim()
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Get-PythonCandidate {
    param([string]$Path, [string[]]$Prefix = @())
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    try {
        $versionArguments = @($Prefix) + @("--version")
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $versionOutput = & $Path @versionArguments 2>&1 | Out-String
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        $version = $versionOutput.Trim()
        if ($version -match "Python 3\.11\.") {
            return [pscustomobject]@{
                Path = $Path
                Prefix = @($Prefix)
                Version = $version
            }
        }
    } catch {
        return $null
    }
    return $null
}

function Find-Python311 {
    $candidates = @()
    if ($env:TOOL_DEFECT_PYTHON) {
        $candidates += @{ Path = $env:TOOL_DEFECT_PYTHON; Prefix = @() }
    }
    $py = Get-CommandPath "py"
    if ($py) { $candidates += @{ Path = $py; Prefix = @("-3.11") } }
    foreach ($name in @("python3.11", "python")) {
        $path = Get-CommandPath $name
        if ($path) { $candidates += @{ Path = $path; Prefix = @() } }
    }
    foreach ($path in @(
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
        "C:\Program Files\Python311\python.exe",
        "C:\Python311\python.exe"
    )) {
        $candidates += @{ Path = $path; Prefix = @() }
    }
    foreach ($candidate in $candidates) {
        $result = Get-PythonCandidate -Path $candidate.Path -Prefix $candidate.Prefix
        if ($result) { return $result }
    }
    return $null
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($machinePath -and $userPath) {
        $env:Path = "$machinePath;$userPath"
    } elseif ($machinePath) {
        $env:Path = $machinePath
    } elseif ($userPath) {
        $env:Path = $userPath
    }
}

function Get-PreferredNodePath {
    $portableNode = Join-Path $NodeHome "node.exe"
    if (Test-Path -LiteralPath $portableNode) { return $portableNode }
    return Get-CommandPath "node"
}

function Get-CorepackPath {
    param([string]$NodeDirectory)
    foreach ($name in @("corepack.cmd", "corepack.exe", "corepack.ps1")) {
        $candidate = Join-Path $NodeDirectory $name
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Get-PnpmShimPath {
    return (Join-Path $PnpmHome "pnpm.cmd")
}

function Test-IsPnpmShim {
    param([string]$Runner)
    if (-not $Runner) { return $false }
    return ([IO.Path]::GetFullPath($Runner) -eq [IO.Path]::GetFullPath((Get-PnpmShimPath)))
}

function Get-PnpmVersion {
    param([string]$Runner)
    if (Test-IsPnpmShim -Runner $Runner) {
        return (Get-ToolVersion -Path $Runner -Argument "--version")
    }
    return (Get-ToolVersion -Path $Runner -Argument "pnpm" -ExtraArgument "--version")
}

function Install-PnpmWithNpm {
    $node = Get-PreferredNodePath
    if (-not $node) { Stop-WithError "Node.js is missing before npm fallback setup." }
    $npm = Join-Path (Split-Path -Parent $node) "npm.cmd"
    if (-not (Test-Path -LiteralPath $npm)) {
        Stop-WithError "npm.cmd is missing beside the selected Node.js installation."
    }
    $pnpmCli = Join-Path $PnpmHome "node_modules\pnpm\bin\pnpm.cjs"
    $npmCache = Join-Path $ProjectRoot ".build\toolchains\npm-cache"
    New-Item -ItemType Directory -Path $PnpmHome -Force | Out-Null
    New-Item -ItemType Directory -Path $npmCache -Force | Out-Null
    $env:NPM_CONFIG_CACHE = $npmCache
    $arguments = @(
        "install", "--prefix", $PnpmHome, "--no-save", "--no-package-lock",
        "--ignore-scripts", "pnpm@$PnpmVersion"
    )
    if ($env:COREPACK_NPM_REGISTRY) {
        $arguments += @("--registry", $env:COREPACK_NPM_REGISTRY)
    }
    Write-Host "[setup] Falling back to npm for pnpm $PnpmVersion." -ForegroundColor Yellow
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $npm @arguments 2>&1 | ForEach-Object { Write-Host $_ }
        $npmExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($npmExitCode -ne 0 -or -not (Test-Path -LiteralPath $pnpmCli)) {
        Stop-WithError "npm fallback could not install pnpm $PnpmVersion. Check registry, proxy, or firewall access."
    }
    $shim = Get-PnpmShimPath
    $shimContent = @"
@echo off
setlocal
if /I "%~1"=="pnpm" shift
"$node" "$pnpmCli" %*
exit /b %ERRORLEVEL%
"@
    Set-Content -LiteralPath $shim -Value $shimContent -Encoding ascii
    return $shim
}

function Install-PortableNode {
    $toolRoot = Split-Path -Parent $NodeHome
    $archivePath = Join-Path $toolRoot $NodeArchiveName
    New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
    Write-Host "[setup] Downloading Node.js $NodeVersion portable x64 toolchain." -ForegroundColor Cyan
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $NodeArchiveUrl -OutFile $archivePath
        $checksumText = (Invoke-WebRequest -UseBasicParsing -Uri $NodeChecksumsUrl).Content
        $checksumLine = $checksumText -split "`r?`n" |
            Where-Object { $_ -match ("^\s*[0-9a-fA-F]{64}\s+\*?" + [regex]::Escape($NodeArchiveName) + "\s*$") } |
            Select-Object -First 1
        if (-not $checksumLine) {
            Stop-WithError "Could not find the official SHA256 entry for $NodeArchiveName."
        }
        $expectedHash = ([regex]::Match($checksumLine, "[0-9a-fA-F]{64}")).Value.ToLowerInvariant()
        $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            Stop-WithError "Node.js archive SHA256 verification failed."
        }
        Expand-Archive -LiteralPath $archivePath -DestinationPath $toolRoot -Force
    } catch {
        Stop-WithError ("Could not prepare portable Node.js {0}: {1}" -f $NodeVersion, $_.Exception.Message)
    }
    $portableNode = Join-Path $NodeHome "node.exe"
    if (-not (Test-Path -LiteralPath $portableNode)) {
        Stop-WithError "Portable Node.js extraction completed without node.exe: $NodeHome"
    }
}

function Install-WingetPackage {
    param([string]$Id, [string]$Version = $null)
    $winget = Get-CommandPath "winget"
    if (-not $winget) {
        Stop-WithError "winget is not available. Install App Installer and retry, or install $Id manually."
    }
    $arguments = @(
        "install", "--id", $Id, "--exact", "--source", "winget",
        "--accept-package-agreements", "--accept-source-agreements"
    )
    if ($Version) { $arguments += @("--version", $Version) }
    & $winget @arguments
    $exitCode = $LASTEXITCODE
    Refresh-ProcessPath
    if ($exitCode -ne 0) {
        Write-Warning "winget did not install or upgrade $Id (exit code $exitCode). The prerequisite will be validated again."
    }
}

function Ensure-Python311 {
    $python = Find-Python311
    if (-not $python -and $InstallPrerequisites) {
        Install-WingetPackage -Id "Python.Python.3.11"
        $python = Find-Python311
    }
    if (-not $python) {
        Stop-WithError "Python 3.11.x is required. The current Python 3.9/3.13 environment is not accepted."
    }
    Write-Host "[setup] Python: $($python.Version) [$($python.Path)]" -ForegroundColor Green
    return $python
}

function Ensure-Node {
    $node = Get-PreferredNodePath
    $version = Get-ToolVersion -Path $node -Argument "--version"
    if ($version -ne "v$NodeVersion" -and $InstallPrerequisites) {
        Install-PortableNode
        $node = Get-PreferredNodePath
        $version = Get-ToolVersion -Path $node -Argument "--version"
    }
    if ($version -ne "v$NodeVersion") {
        Stop-WithError "Node.js $NodeVersion is required; detected [$version]."
    }
    $nodeDirectory = Split-Path -Parent $node
    $env:Path = "$nodeDirectory;$env:Path"
    Write-Host "[setup] Node.js: $version" -ForegroundColor Green
    return $node
}

function Find-Java25 {
    $pairs = @()
    $pathJava = Get-CommandPath "java"
    $pathJavac = Get-CommandPath "javac"
    if ($pathJava -and $pathJavac) {
        $pairs += [pscustomobject]@{ Java = $pathJava; Javac = $pathJavac }
    }
    foreach ($root in @("C:\Program Files\Eclipse Adoptium", "C:\Program Files\Java")) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $directories = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "jdk-25" } |
            Sort-Object FullName -Descending
        foreach ($directory in $directories) {
            $java = Join-Path $directory.FullName "bin\java.exe"
            $javac = Join-Path $directory.FullName "bin\javac.exe"
            if ((Test-Path -LiteralPath $java) -and (Test-Path -LiteralPath $javac)) {
                $pairs += [pscustomobject]@{ Java = $java; Javac = $javac }
            }
        }
    }
    foreach ($pair in $pairs) {
        $versionOutput = Get-ToolVersion -Path $pair.Java -Argument "-version"
        $compilerOutput = Get-ToolVersion -Path $pair.Javac -Argument "-version"
        if ($versionOutput.Contains("25.") -and $compilerOutput.Contains("25.")) {
            return $pair
        }
    }
    return $null
}

function Ensure-Java25 {
    $java = Find-Java25
    if (-not $java -and $InstallPrerequisites) {
        Install-WingetPackage -Id "EclipseAdoptium.Temurin.25.JDK"
        Refresh-ProcessPath
        $java = Find-Java25
    }
    if (-not $java) {
        Stop-WithError "Java 25 is required for the business API; java and javac must both be 25.x."
    }
    Write-Host "[setup] Java: 25.x [$($java.Java)]" -ForegroundColor Green
}

function Ensure-VirtualEnvironment {
    param([string]$VenvPath, [object]$Python)
    $pythonPath = Join-Path $VenvPath "Scripts\python.exe"
    if (Test-Path -LiteralPath $VenvPath) {
        $existingVersion = ""
        if (Test-Path -LiteralPath $pythonPath) {
            $existingVersion = Get-ToolVersion -Path $pythonPath -Argument "--version"
        }
        if ($existingVersion -notmatch "Python 3\.11\.") {
            $backup = "$VenvPath.backup.$(Get-Date -Format yyyyMMddHHmmssfff)"
            Move-Item -LiteralPath $VenvPath -Destination $backup
            Write-Host "[setup] Moved incompatible venv to $backup" -ForegroundColor Yellow
        }
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host "[setup] Creating venv: $VenvPath" -ForegroundColor Cyan
        $venvArguments = @($Python.Prefix) + @("-m", "venv", $VenvPath)
        Invoke-Checked -FilePath $Python.Path -Arguments $venvArguments -Label "create Python venv"
    }
    $actual = Get-ToolVersion -Path $pythonPath -Argument "--version"
    if ($actual -notmatch "Python 3\.11\.") {
        Stop-WithError "$VenvPath is not a Python 3.11 venv: $actual"
    }
    return $pythonPath
}

function Invoke-VenvPip {
    param([string]$PythonPath, [string[]]$Arguments)
    $pipArguments = @("-m", "pip") + @($Arguments)
    Invoke-Checked -FilePath $PythonPath -Arguments $pipArguments -Label "Python pip"
}

function Install-PythonEnvironment {
    param(
        [string]$PythonPath,
        [string[]]$Requirements,
        [string[]]$EditablePackages,
        [switch]$InstallEditableBeforeRequirements
    )
    Invoke-VenvPip -PythonPath $PythonPath -Arguments @("install", "--upgrade", "pip")
    if ($InstallEditableBeforeRequirements) {
        # The edge lock contains a pin for a workspace package. Register it
        # before pip resolves the lock so pip does not query PyPI for it.
        foreach ($package in $EditablePackages) {
            $packagePath = Join-Path $ProjectRoot $package
            Invoke-VenvPip -PythonPath $PythonPath -Arguments @("install", "--no-deps", "-e", $packagePath)
        }
    }
    foreach ($requirement in $Requirements) {
        $requirementPath = Join-Path $ProjectRoot $requirement
        Invoke-VenvPip -PythonPath $PythonPath -Arguments @("install", "-r", $requirementPath)
    }
    if (-not $InstallEditableBeforeRequirements) {
        foreach ($package in $EditablePackages) {
            $packagePath = Join-Path $ProjectRoot $package
            Invoke-VenvPip -PythonPath $PythonPath -Arguments @("install", "--no-deps", "-e", $packagePath)
        }
    }
}

function Ensure-Pnpm {
    New-Item -ItemType Directory -Path $CorepackHome -Force | Out-Null
    New-Item -ItemType Directory -Path $NativeTempHome -Force | Out-Null
    $env:COREPACK_HOME = $CorepackHome
    $env:TEMP = $NativeTempHome
    $env:TMP = $NativeTempHome
    $node = Get-PreferredNodePath
    if (-not $node) { Stop-WithError "Node.js is missing before pnpm setup." }
    $corepack = Get-CorepackPath -NodeDirectory (Split-Path -Parent $node)
    if (-not $corepack) {
        Stop-WithError "corepack is missing beside the selected Node.js installation."
    }
    $existingShim = Get-PnpmShimPath
    if (Test-Path -LiteralPath $existingShim) {
        $existingVersion = Get-PnpmVersion -Runner $existingShim
        if ($existingVersion -eq $PnpmVersion) {
            Write-Host "[setup] pnpm: $existingVersion (local npm fallback)" -ForegroundColor Green
            return $existingShim
        }
    }
    $runner = $null
    try {
        Invoke-Checked -FilePath $corepack -Arguments @("enable") -Label "corepack enable"
        Invoke-Checked -FilePath $corepack -Arguments @("prepare", "pnpm@$PnpmVersion", "--activate") -Label "prepare pnpm"
        $runner = $corepack
    } catch {
        Write-Warning "Corepack could not download pnpm; using npm fallback."
        $runner = Install-PnpmWithNpm
    }
    $version = Get-PnpmVersion -Runner $runner
    if ($version -ne $PnpmVersion) {
        Stop-WithError "pnpm $PnpmVersion is required; detected [$version]."
    }
    Write-Host "[setup] pnpm: $version" -ForegroundColor Green
    return $runner
}

function Install-Frontend {
    param([string]$Corepack)
    foreach ($directory in @("packages\typescript-contracts", "apps\web-console")) {
        $directoryPath = Join-Path $ProjectRoot $directory
        $arguments = @("--dir", $directoryPath, "install", "--frozen-lockfile")
        if (-not (Test-IsPnpmShim -Runner $Corepack)) {
            $arguments = @("pnpm") + $arguments
        }
        Invoke-Checked -FilePath $Corepack -Arguments $arguments -Label "install frontend dependencies"
    }
}

try {
    Set-Location $ProjectRoot
    Write-Host "=== Tool Defect native Windows setup ===" -ForegroundColor Cyan
    Write-Host "Docker and WSL are not used by this script." -ForegroundColor DarkGray

    $python = Ensure-Python311
    if (-not $SkipJava) { Ensure-Java25 }
    $corepack = $null
    if (-not $SkipFrontend) {
        Ensure-Node | Out-Null
        $corepack = Ensure-Pnpm
    }

    $rootVenv = Ensure-VirtualEnvironment -VenvPath (Join-Path $ProjectRoot ".venv") -Python $python
    $rootRequirements = @("requirements.txt")
    if ($IncludeLegacyGui) { $rootRequirements = @("requirements-app.txt") }
    Install-PythonEnvironment -PythonPath $rootVenv -Requirements $rootRequirements -EditablePackages @(
        ".", "packages\python-contracts", "services\inference-service", "apps\edge-agent", "jobs\artifact-migrator"
    )

    if (-not $SkipEdgeEnvironment) {
        $edgeVenv = Ensure-VirtualEnvironment -VenvPath (Join-Path $ProjectRoot "apps\edge-agent\.venv") -Python $python
        Install-PythonEnvironment -PythonPath $edgeVenv -Requirements @("requirements\edge.lock") -EditablePackages @("packages\python-contracts", "apps\edge-agent") -InstallEditableBeforeRequirements
    }

    if (-not $SkipInferenceEnvironment) {
        $inferenceVenv = Ensure-VirtualEnvironment -VenvPath (Join-Path $ProjectRoot "services\inference-service\.venv") -Python $python
        Install-PythonEnvironment -PythonPath $inferenceVenv -Requirements @("requirements.txt", "requirements\inference.lock") -EditablePackages @(".", "services\inference-service")
    }

    if (-not $SkipFrontend) { Install-Frontend -Corepack $corepack }

    Write-Host "[OK] Native Windows environment setup completed." -ForegroundColor Green
    Write-Host "Example: .\run-windows.bat start -EnvFile .windows.env.ps1"
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
