#Requires -Version 5.1
<#
.SYNOPSIS
    Install and manage the native Windows development infrastructure.

.DESCRIPTION
    This entry point provisions the eight local development infrastructure
    services used by run-windows.ps1. It does not use Docker or WSL.

    The installation is intended for local development and evaluation only.
    MinIO on Windows is not a production deployment target.
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [ValidateSet("install", "status", "uninstall", "help")]
    [string]$Action = "install",
    [string]$InstallRoot,
    [string]$EnvFile,
    [ValidateSet("none", "postgres", "rabbitmq", "minio", "monitoring")]
    [string]$StartAt = "none",
    [switch]$SkipDownloads,
    [switch]$ResumePartial
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = Join-Path $ProjectRoot ".build\windows-infrastructure"
}
if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $ProjectRoot ".windows.env.ps1"
}
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$EnvFile = [IO.Path]::GetFullPath($EnvFile)

$DownloadRoot = Join-Path $InstallRoot "downloads"
$PackageRoot = Join-Path $InstallRoot "packages"
$ServiceRoot = Join-Path $InstallRoot "services"
$DataRoot = Join-Path $InstallRoot "data"
$ConfigRoot = Join-Path $InstallRoot "config"
$LogRoot = Join-Path $InstallRoot "logs"
$StatePath = Join-Path $InstallRoot "install-state.json"
$PartialStatePath = Join-Path $InstallRoot "install-in-progress.json"
$StateVersion = 1
$script:CreatedServiceEntries = @()

$ServiceDefinitions = @(
    [pscustomobject]@{ Key = "postgres"; ServiceName = "ToolDefect-PostgreSQL"; Label = "PostgreSQL"; Port = 5432; HealthUrl = $null; Kind = "postgres" }
    [pscustomobject]@{ Key = "rabbitmq"; ServiceName = "ToolDefect-RabbitMQ"; Label = "RabbitMQ"; Port = 5672; HealthUrl = "http://127.0.0.1:15672/"; Kind = "rabbitmq" }
    [pscustomobject]@{ Key = "object-storage"; ServiceName = "ToolDefect-MinIO"; Label = "Object storage"; Port = 9000; HealthUrl = "http://127.0.0.1:9000/minio/health/live"; Kind = "winsw" }
    [pscustomobject]@{ Key = "telemetry"; ServiceName = "ToolDefect-OTel"; Label = "OpenTelemetry collector"; Port = 4317; HealthUrl = $null; Kind = "winsw" }
    [pscustomobject]@{ Key = "prometheus"; ServiceName = "ToolDefect-Prometheus"; Label = "Prometheus"; Port = 9090; HealthUrl = "http://127.0.0.1:9090/-/ready"; Kind = "winsw" }
    [pscustomobject]@{ Key = "grafana"; ServiceName = "ToolDefect-Grafana"; Label = "Grafana"; Port = 3000; HealthUrl = "http://127.0.0.1:3000/api/health"; Kind = "winsw" }
    [pscustomobject]@{ Key = "loki"; ServiceName = "ToolDefect-Loki"; Label = "Loki"; Port = 3100; HealthUrl = "http://127.0.0.1:3100/ready"; Kind = "winsw" }
    [pscustomobject]@{ Key = "tempo"; ServiceName = "ToolDefect-Tempo"; Label = "Tempo"; Port = 3200; HealthUrl = "http://127.0.0.1:3200/ready"; Kind = "winsw" }
)

$ArtifactDefinitions = @(
    [pscustomobject]@{
        Key = "postgres"; Version = "18.4"; FileName = "postgresql-18.4-1-windows-x64-binaries.zip"
        Url = "https://get.enterprisedb.com/postgresql/postgresql-18.4-1-windows-x64-binaries.zip"
        ExpectedSha256 = "7EFFE34C0BF89027B3F171447D351CBC460F4566C8D0F643DAEC67F140787858"
        Type = "zip"
    }
    [pscustomobject]@{
        Key = "erlang"; Version = "27.3.4.15"; FileName = "otp_win64_27.3.4.15.zip"
        Url = "https://github.com/erlang/otp/releases/download/OTP-27.3.4.15/otp_win64_27.3.4.15.zip"
        ExpectedSha256 = "5376463FC814DF10DF54B53C9D8924782EF02749052BA9069CBCDFF5C6491B64"
        Type = "zip"
    }
    [pscustomobject]@{
        Key = "rabbitmq"; Version = "4.1.2"; FileName = "rabbitmq-server-windows-4.1.2.zip"
        Url = "https://github.com/rabbitmq/rabbitmq-server/releases/download/v4.1.2/rabbitmq-server-windows-4.1.2.zip"
        ExpectedSha256 = "6E66290C1A568F88A14E894ADC88F0699A7F21956594C302BA71E97AD9B28AF6"
        Type = "zip"
    }
    [pscustomobject]@{
        Key = "minio"; Version = "RELEASE.2025-07-23T15-54-02Z"; FileName = "minio.RELEASE.2025-07-23T15-54-02Z"
        Url = "https://dl.min.io/server/minio/release/windows-amd64/archive/minio.RELEASE.2025-07-23T15-54-02Z"
        ChecksumUrl = "https://dl.min.io/server/minio/release/windows-amd64/archive/minio.RELEASE.2025-07-23T15-54-02Z.sha256sum"
        Type = "file"
    }
    [pscustomobject]@{
        Key = "otel"; Version = "0.157.0"; FileName = "otelcol-contrib_0.157.0_windows_amd64.tar.gz"
        Url = "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.157.0/otelcol-contrib_0.157.0_windows_amd64.tar.gz"
        ExpectedSha256 = "7B3938E1522FF04261A694A58E7111C5F7CDD19BE617C3A77118CFFAD7ABB815"
        Type = "tar.gz"
    }
    [pscustomobject]@{
        Key = "prometheus"; Version = "3.5.0"; FileName = "prometheus-3.5.0.windows-amd64.zip"
        Url = "https://github.com/prometheus/prometheus/releases/download/v3.5.0/prometheus-3.5.0.windows-amd64.zip"
        ExpectedSha256 = "B3C2607D1E80A277735FD3CDE86432EB1B6843897CB82FB04FBF4C7FFB1D1C36"
        Type = "zip"
    }
    [pscustomobject]@{
        Key = "grafana"; Version = "12.1.0"; FileName = "grafana-12.1.0.windows-amd64.zip"
        Url = "https://dl.grafana.com/oss/release/grafana-12.1.0.windows-amd64.zip"
        ChecksumUrl = "https://dl.grafana.com/oss/release/grafana-12.1.0.windows-amd64.zip.sha256"
        Type = "zip"
    }
    [pscustomobject]@{
        Key = "loki"; Version = "3.7.0"; FileName = "loki-windows-amd64.exe.zip"
        Url = "https://github.com/grafana/loki/releases/download/v3.7.0/loki-windows-amd64.exe.zip"
        ExpectedSha256 = "D5F1D36BF57860894F39AE63591E035ABEAFC13011BE3CD857046C1C12701A3F"
        Type = "zip"
    }
    [pscustomobject]@{
        Key = "tempo"; Version = "3.0.0"; FileName = "tempo_3.0.0_windows_amd64.tar.gz"
        Url = "https://github.com/grafana/tempo/releases/download/v3.0.0/tempo_3.0.0_windows_amd64.tar.gz"
        ExpectedSha256 = "10AE97BAE2848FB092300A76695D7BCDE590FE8E4540166347CBBC556DE8B1B2"
        Type = "tar.gz"
    }
    [pscustomobject]@{
        Key = "winsw"; Version = "2.12.0"; FileName = "WinSW.NET461.exe"
        Url = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET461.exe"
        ExpectedSha256 = "B5066B7BBDFBA1293E5D15CDA3CAAEA88FBEAB35BD5B38C41C913D492AADFC4F"
        Type = "file"
    }
)

function Stop-WithError {
    param([string]$Message)
    throw "[WINDOWS-INFRA-FAILED] $Message"
}

function Write-Info {
    param([string]$Message)
    Write-Host "[infra] $Message" -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Message)
    Write-Warning "[WINDOWS-INFRA-HOLD] $Message"
}

function Ensure-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Stop-WithError "Administrator privileges are required. Open PowerShell as Administrator and rerun this script."
    }
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$Label = $FilePath,
        [string]$WorkingDirectory = $null
    )
    if (-not (Test-Path -LiteralPath $FilePath) -and -not (Get-Command $FilePath -ErrorAction SilentlyContinue)) {
        Stop-WithError "Executable is missing: $FilePath"
    }
    if ($WorkingDirectory) {
        Push-Location $WorkingDirectory
    }
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError "$Label failed with exit code $LASTEXITCODE."
        }
    } finally {
        if ($WorkingDirectory) { Pop-Location }
    }
}

function Get-ArtifactExpectedHash {
    param($Artifact)
    if ($Artifact.ExpectedSha256) {
        return $Artifact.ExpectedSha256.ToUpperInvariant()
    }
    if (-not $Artifact.ChecksumUrl) {
        Stop-WithError "No SHA-256 source is configured for artifact $($Artifact.Key)."
    }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Artifact.ChecksumUrl
        $text = if ($response.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($response.Content) } else { [string]$response.Content }
    } catch {
        Stop-WithError "Unable to download checksum for $($Artifact.Key): $($_.Exception.Message)"
    }
    $escapedName = [regex]::Escape($Artifact.FileName)
    $match = [regex]::Match($text, "(?im)(?<hash>[0-9a-f]{64})\s+\*?$escapedName")
    if (-not $match.Success) {
        $match = [regex]::Match($text, "(?im)(?<hash>[0-9a-f]{64})")
    }
    if (-not $match.Success) {
        Stop-WithError "Checksum source did not contain a SHA-256 value for $($Artifact.FileName)."
    }
    return $match.Groups["hash"].Value.ToUpperInvariant()
}

function Download-Artifact {
    param($Artifact)
    Ensure-Directory $DownloadRoot
    $destination = Join-Path $DownloadRoot $Artifact.FileName
    $expected = Get-ArtifactExpectedHash -Artifact $Artifact
    if (Test-Path -LiteralPath $destination) {
        $existing = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($existing -ne $expected) {
            Stop-WithError "SHA-256 mismatch for existing artifact $($Artifact.FileName). Refusing to overwrite it."
        }
        return $destination
    }
    $partial = "$destination.partial"
    if (Test-Path -LiteralPath $partial) {
        Remove-Item -LiteralPath $partial -Force
    }
    Write-Info "Downloading $($Artifact.Key) $($Artifact.Version)."
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Artifact.Url -OutFile $partial
        $actual = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($actual -ne $expected) {
            Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
            Stop-WithError "SHA-256 mismatch for $($Artifact.FileName)."
        }
        Move-Item -LiteralPath $partial -Destination $destination
    } catch {
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        if ($_.Exception.Message.StartsWith("[WINDOWS-INFRA-FAILED]", [StringComparison]::Ordinal)) { throw }
        Stop-WithError "Download failed for $($Artifact.FileName): $($_.Exception.Message)"
    }
    return $destination
}

function Use-CachedArtifact {
    param($Artifact)
    $destination = Join-Path $DownloadRoot $Artifact.FileName
    if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
        Stop-WithError "Cached artifact is missing while -SkipDownloads was specified: $destination"
    }
    $expected = Get-ArtifactExpectedHash -Artifact $Artifact
    $actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -ne $expected) {
        Stop-WithError "SHA-256 mismatch for cached artifact $($Artifact.FileName). Refusing to use it."
    }
    Write-Info "Using verified cached $($Artifact.Key) $($Artifact.Version)."
    return $destination
}

function Expand-ArchiveArtifact {
    param([string]$ArchivePath, [string]$Destination, [string]$Type)
    if (Test-Path -LiteralPath $Destination) {
        return $Destination
    }
    Ensure-Directory $Destination
    if ($Type -eq "zip") {
        Expand-Archive -LiteralPath $ArchivePath -DestinationPath $Destination -Force
    } elseif ($Type -eq "tar.gz") {
        $systemTar = Join-Path $env:SystemRoot "System32\tar.exe"
        $tar = if (Test-Path -LiteralPath $systemTar) { Get-Item -LiteralPath $systemTar } else { Get-Command tar.exe -ErrorAction SilentlyContinue }
        if ($null -eq $tar) {
            Stop-WithError "tar.exe is required to extract $ArchivePath."
        }
        $tarPath = if ($tar.PSObject.Properties.Name -contains "Source") { $tar.Source } else { $tar.FullName }
        Invoke-Checked -FilePath $tarPath -Arguments @("-xzf", $ArchivePath, "-C", $Destination) -Label "extract $ArchivePath"
    } else {
        Stop-WithError "Unsupported archive type: $Type"
    }
    return $Destination
}

function Find-FileUnder {
    param([string]$Root, [string]$Name)
    $found = Get-ChildItem -LiteralPath $Root -Recurse -File -Filter $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $found) {
        Stop-WithError "Expected file was not found after extraction: $Name"
    }
    return $found.FullName
}

function Find-ErlangHome {
    param([string]$Root)
    $candidates = @()
    if (Test-Path -LiteralPath $Root -PathType Container) {
        $candidates += Get-Item -LiteralPath $Root
        $candidates += @(Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue)
    }
    $erlangHomeItem = $candidates |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "bin\erl.exe") } |
        Select-Object -First 1
    if ($null -eq $erlangHomeItem) {
        Stop-WithError "Erlang installation is incomplete: bin\erl.exe was not found under $Root."
    }
    return $erlangHomeItem.FullName
}

function Escape-Xml {
    param([string]$Value)
    return [Security.SecurityElement]::Escape($Value)
}

function Convert-ToYamlPath {
    param([string]$Path)
    return $Path.Replace("\", "/")
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Value)
    [IO.File]::WriteAllText($Path, $Value, [Text.UTF8Encoding]::new($false))
}

function Set-RestrictedAcl {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
    $identityName = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $systemSid = New-Object Security.Principal.SecurityIdentifier -ArgumentList @("S-1-5-18")
    $administratorsSid = New-Object Security.Principal.SecurityIdentifier -ArgumentList @("S-1-5-32-544")
    $identities = @($identityName, $systemSid, $administratorsSid)
    if ($item.PSIsContainer) {
        $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
        $propagation = [Security.AccessControl.PropagationFlags]::None
        $rules = @($identities | ForEach-Object {
            New-Object Security.AccessControl.FileSystemAccessRule -ArgumentList @($_, "FullControl", $inheritance, $propagation, "Allow")
        })
    } else {
        $rules = @($identities | ForEach-Object {
            New-Object Security.AccessControl.FileSystemAccessRule -ArgumentList @($_, "FullControl", "Allow")
        })
    }
    foreach ($rule in $rules) { $acl.AddAccessRule($rule) }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function New-RandomSecret {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($buffer) -replace "-", "").ToLowerInvariant()
}

function Read-GeneratedEnvironment {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*\$env:(?<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"(?<value>[^"]*)"\s*$') {
            $values[$Matches.name] = $Matches.value
        }
    }
    return $values
}

function Write-EnvironmentFile {
    param([hashtable]$Values, [switch]$CreatedByThisRun)
    if ((Test-Path -LiteralPath $EnvFile) -and -not $CreatedByThisRun) {
        Stop-WithError "Environment file already exists but is not owned by this installer: $EnvFile"
    }
    $parent = Split-Path -Parent $EnvFile
    Ensure-Directory $parent
    $lines = @(
        '# Generated by setup-windows-infrastructure.ps1. Do not commit this file.'
        ('$env:TD_DATABASE_URL = "{0}"' -f $Values.TD_DATABASE_URL)
        ('$env:TD_DATABASE_USERNAME = "{0}"' -f $Values.TD_DATABASE_USERNAME)
        ('$env:TD_DATABASE_PASSWORD = "{0}"' -f $Values.TD_DATABASE_PASSWORD)
        ('$env:TD_RABBITMQ_ADDRESSES = "{0}"' -f $Values.TD_RABBITMQ_ADDRESSES)
        ('$env:TD_RABBITMQ_USERNAME = "{0}"' -f $Values.TD_RABBITMQ_USERNAME)
        ('$env:TD_RABBITMQ_PASSWORD = "{0}"' -f $Values.TD_RABBITMQ_PASSWORD)
        ('$env:TD_RABBITMQ_SSL_ENABLED = "false"')
        ('$env:TD_S3_ENDPOINT = "{0}"' -f $Values.TD_S3_ENDPOINT)
        ('$env:TD_S3_ACCESS_KEY = "{0}"' -f $Values.TD_S3_ACCESS_KEY)
        ('$env:TD_S3_SECRET_KEY = "{0}"' -f $Values.TD_S3_SECRET_KEY)
        ('$env:TD_S3_REQUIRE_TLS = "false"')
        ('$env:TD_S3_PATH_STYLE = "true"')
        ('$env:TD_MESSAGING_ENABLED = "true"')
        ('$env:TD_STORAGE_ENABLED = "true"')
        ('$env:TD_OPERATIONS_ENABLED = "true"')
        ('$env:TD_AUTH_SECURE_COOKIE = "false"')
        ('$env:TD_MANAGEMENT_PORT = "9091"')
        ('$env:TD_ENVIRONMENT = "development"')
        ('$env:TD_SERVICE_VERSION = "workspace"')
        ('$env:TD_GRAFANA_ADMIN_USER = "{0}"' -f $Values.TD_GRAFANA_ADMIN_USER)
        ('$env:TD_GRAFANA_ADMIN_PASSWORD = "{0}"' -f $Values.TD_GRAFANA_ADMIN_PASSWORD)
    )
    foreach ($definition in $ServiceDefinitions) {
        $name = switch ($definition.Key) {
            "postgres" { "TD_WINDOWS_POSTGRES_SERVICE" }
            "rabbitmq" { "TD_WINDOWS_RABBITMQ_SERVICE" }
            "object-storage" { "TD_WINDOWS_OBJECT_STORAGE_SERVICE" }
            "telemetry" { "TD_WINDOWS_OTEL_SERVICE" }
            "prometheus" { "TD_WINDOWS_PROMETHEUS_SERVICE" }
            "grafana" { "TD_WINDOWS_GRAFANA_SERVICE" }
            "loki" { "TD_WINDOWS_LOKI_SERVICE" }
            "tempo" { "TD_WINDOWS_TEMPO_SERVICE" }
        }
        $lines += ('$env:{0} = "{1}"' -f $name, $definition.ServiceName)
    }
    $temporary = "$EnvFile.partial"
    try {
        Set-Content -LiteralPath $temporary -Value $lines -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $EnvFile -Force
        Set-RestrictedAcl -Path $EnvFile
    } catch {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Get-EnvironmentValues {
    param([hashtable]$Existing)
    $required = @(
        "TD_DATABASE_URL", "TD_DATABASE_USERNAME", "TD_DATABASE_PASSWORD",
        "TD_RABBITMQ_ADDRESSES", "TD_RABBITMQ_USERNAME", "TD_RABBITMQ_PASSWORD",
        "TD_S3_ENDPOINT", "TD_S3_ACCESS_KEY", "TD_S3_SECRET_KEY",
        "TD_GRAFANA_ADMIN_USER", "TD_GRAFANA_ADMIN_PASSWORD",
        "TD_MESSAGING_ENABLED", "TD_STORAGE_ENABLED", "TD_OPERATIONS_ENABLED"
    )
    foreach ($name in $required) {
        if (-not $Existing.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($Existing[$name])) {
            Stop-WithError "Environment file is missing a non-empty value: $name"
        }
    }
    foreach ($definition in $ServiceDefinitions) {
        $name = switch ($definition.Key) {
            "postgres" { "TD_WINDOWS_POSTGRES_SERVICE" }
            "rabbitmq" { "TD_WINDOWS_RABBITMQ_SERVICE" }
            "object-storage" { "TD_WINDOWS_OBJECT_STORAGE_SERVICE" }
            "telemetry" { "TD_WINDOWS_OTEL_SERVICE" }
            "prometheus" { "TD_WINDOWS_PROMETHEUS_SERVICE" }
            "grafana" { "TD_WINDOWS_GRAFANA_SERVICE" }
            "loki" { "TD_WINDOWS_LOKI_SERVICE" }
            "tempo" { "TD_WINDOWS_TEMPO_SERVICE" }
        }
        if (-not $Existing.ContainsKey($name) -or $Existing[$name] -ne $definition.ServiceName) {
            Stop-WithError "Environment file service name does not match the managed service: $name"
        }
    }
    return $Existing
}

function New-EnvironmentValues {
    return @{
        TD_DATABASE_URL = "jdbc:postgresql://127.0.0.1:5432/tool_defect"
        TD_DATABASE_USERNAME = "tool_defect"
        TD_DATABASE_PASSWORD = New-RandomSecret
        TD_RABBITMQ_ADDRESSES = "127.0.0.1:5672"
        TD_RABBITMQ_USERNAME = "tool_defect"
        TD_RABBITMQ_PASSWORD = New-RandomSecret
        TD_S3_ENDPOINT = "http://127.0.0.1:9000"
        TD_S3_ACCESS_KEY = "td_$(New-RandomSecret -Bytes 12)"
        TD_S3_SECRET_KEY = New-RandomSecret
        TD_GRAFANA_ADMIN_USER = "td_$(New-RandomSecret -Bytes 12)"
        TD_GRAFANA_ADMIN_PASSWORD = New-RandomSecret
    }
}

function Get-InstallStageForService {
    param([string]$Key)
    switch ($Key) {
        "postgres" { return "postgres" }
        "rabbitmq" { return "rabbitmq" }
        "object-storage" { return "minio" }
        default { return "monitoring" }
    }
}

function Get-InstallStageForPort {
    param([int]$Port)
    switch ($Port) {
        15672 { return "rabbitmq" }
        9001 { return "minio" }
        default { return "monitoring" }
    }
}

function Should-InstallStage {
    param([string]$Stage)
    if ($StartAt -eq "none") { return $true }
    $stages = @("postgres", "rabbitmq", "minio", "monitoring")
    return ([array]::IndexOf($stages, $Stage) -ge [array]::IndexOf($stages, $StartAt))
}

function Ensure-SkippedServiceReady {
    param($Definition)
    $service = Get-Service -Name $Definition.ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $service -or $service.Status -ne "Running") {
        Stop-WithError "Cannot skip $($Definition.Label): service $($Definition.ServiceName) is not Running. Use -StartAt $((Get-InstallStageForService $Definition.Key)) or install the prerequisite first."
    }
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Definition.Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $listener) {
        Stop-WithError "Cannot skip $($Definition.Label): port $($Definition.Port) is not listening."
    }
    if ($Definition.HealthUrl) {
        Wait-ForHttp -Url $Definition.HealthUrl
    }
    Write-Info "Skipping healthy prerequisite: $($Definition.Label)."
}

function Test-ServiceOwnedByInstaller {
    param([string]$ServiceName)
    $service = Get-CimInstance -ClassName Win32_Service -Filter ("Name='{0}'" -f $ServiceName) -ErrorAction SilentlyContinue
    if ($null -eq $service) { return $false }
    $pathName = [string]$service.PathName
    return ($pathName.IndexOf($ServiceRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}

function Test-ServiceConflict {
    param([switch]$ResumeOwnedServices)
    Ensure-WindowsRuntime
    Ensure-WindowsRuntime
    foreach ($definition in $ServiceDefinitions) {
        $stage = Get-InstallStageForService $definition.Key
        if (-not (Should-InstallStage $stage)) {
            Ensure-SkippedServiceReady -Definition $definition
            continue
        }
        $service = Get-Service -Name $definition.ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $service) {
            if ($ResumeOwnedServices -and (Test-ServiceOwnedByInstaller -ServiceName $definition.ServiceName)) {
                Write-Warn "Removing stale service registration from the incomplete installation: $($definition.ServiceName)"
                Remove-ManagedService -Entry $definition
                continue
            }
            Stop-WithError "Managed service name already exists: $($definition.ServiceName)"
        }
    }
    foreach ($definition in $ServiceDefinitions) {
        if (-not (Should-InstallStage (Get-InstallStageForService $definition.Key))) { continue }
        $listener = Get-NetTCPConnection -State Listen -LocalPort $definition.Port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $listener) {
            Stop-WithError "Required port is already listening: $($definition.Port) ($($definition.Label))."
        }
    }
    foreach ($port in @(4318, 4320, 4321, 8888, 8889, 9095, 9096, 15672, 9001)) {
        if (-not (Should-InstallStage (Get-InstallStageForPort $port))) { continue }
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $listener) {
            Stop-WithError "Required supporting port is already listening: $port."
        }
    }
}

function Ensure-WindowsRuntime {
    foreach ($commandName in @("Get-Service", "Start-Service", "Stop-Service", "Get-NetTCPConnection", "Get-Acl", "Set-Acl", "Expand-Archive")) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            Stop-WithError "Required PowerShell command is unavailable: $commandName"
        }
    }
}

function Test-InstallationDirectoryConflict {
    param([switch]$OwnedInstallation)
    if ($OwnedInstallation) { return }
    foreach ($path in @($PackageRoot, $ServiceRoot, $DataRoot, $ConfigRoot, $LogRoot)) {
        if (Test-Path -LiteralPath $path) {
            $children = @(Get-ChildItem -LiteralPath $path -Force -ErrorAction SilentlyContinue)
            if ($children.Count -gt 0) {
                Stop-WithError "Existing installation directory is not owned by this installer: $path"
            }
            Write-Info "Reusing empty installation directory: $path"
        }
    }
}

function Write-NativeConfigs {
    param([hashtable]$Values)
    Ensure-Directory $ConfigRoot
    Ensure-Directory (Join-Path $ConfigRoot "grafana")
    Ensure-Directory (Join-Path $ConfigRoot "grafana\provisioning")
    Ensure-Directory (Join-Path $ConfigRoot "grafana\dashboards")
    Ensure-Directory (Join-Path $ConfigRoot "prometheus")
    $monitoringRoot = Join-Path $ProjectRoot "deploy\monitoring"

    $otel = Get-Content -LiteralPath (Join-Path $ProjectRoot "tools\dev\config\otel-collector.yml") -Raw
    $otel = $otel.Replace("tempo:4317", "127.0.0.1:4320").Replace("http://loki:3100", "http://127.0.0.1:3100")
    Write-Utf8NoBom -Path (Join-Path $ConfigRoot "otel-collector.yml") -Value $otel

    $prometheus = Get-Content -LiteralPath (Join-Path $monitoringRoot "prometheus.yml") -Raw
    $prometheus = $prometheus.Replace("prometheus:9090", "127.0.0.1:9090").Replace("telemetry:8889", "127.0.0.1:8889").Replace("business-api:9091", "127.0.0.1:9091").Replace("inference-service:9092", "127.0.0.1:9092").Replace("edge-agent:9100", "127.0.0.1:9100")
    $prometheus = $prometheus.Replace("/etc/prometheus/rules/*.yml", (Convert-ToYamlPath (Join-Path $ConfigRoot "prometheus\rules.yml")))
    Write-Utf8NoBom -Path (Join-Path $ConfigRoot "prometheus\prometheus.yml") -Value $prometheus
    Copy-Item -LiteralPath (Join-Path $monitoringRoot "alerts.yml") -Destination (Join-Path $ConfigRoot "prometheus\rules.yml") -Force

    $loki = Get-Content -LiteralPath (Join-Path $monitoringRoot "loki.yml") -Raw
    $lokiPath = Convert-ToYamlPath (Join-Path $DataRoot "loki")
    $loki = $loki.Replace("/var/lib/loki", $lokiPath)
    $loki = $loki.Replace("  http_listen_port: 3100", "  http_listen_port: 3100`r`n  grpc_listen_port: 9096")
    Write-Utf8NoBom -Path (Join-Path $ConfigRoot "loki.yml") -Value $loki

    $tempo = Get-Content -LiteralPath (Join-Path $ProjectRoot "tools\dev\config\tempo.yml") -Raw
    $tempoPath = Convert-ToYamlPath (Join-Path $DataRoot "tempo")
    $tempo = $tempo.Replace("/var/lib/tempo", $tempoPath).Replace("endpoint: 0.0.0.0:4317", "endpoint: 127.0.0.1:4320").Replace("endpoint: 0.0.0.0:4318", "endpoint: 127.0.0.1:4321")
    Write-Utf8NoBom -Path (Join-Path $ConfigRoot "tempo.yml") -Value $tempo

    $grafanaSource = Join-Path $monitoringRoot "grafana\provisioning"
    Copy-Item -Path (Join-Path $grafanaSource "*") -Destination (Join-Path $ConfigRoot "grafana\provisioning") -Recurse -Force
    Copy-Item -Path (Join-Path $monitoringRoot "grafana\dashboards\*") -Destination (Join-Path $ConfigRoot "grafana\dashboards") -Recurse -Force
    Get-ChildItem -LiteralPath (Join-Path $ConfigRoot "grafana") -Recurse -File | ForEach-Object {
        $text = Get-Content -LiteralPath $_.FullName -Raw
        $text = $text.Replace("http://prometheus:9090", "http://127.0.0.1:9090").Replace("http://loki:3100", "http://127.0.0.1:3100").Replace("http://tempo:3200", "http://127.0.0.1:3200")
        $text = $text.Replace("/var/lib/grafana/dashboards", (Convert-ToYamlPath (Join-Path $ConfigRoot "grafana\dashboards")))
        Write-Utf8NoBom -Path $_.FullName -Value $text
    }
}

function Get-WinSwPath {
    $artifact = $ArtifactDefinitions | Where-Object Key -eq "winsw"
    $download = Download-Artifact -Artifact $artifact
    Ensure-Directory (Join-Path $ServiceRoot "winsw")
    $path = Join-Path $ServiceRoot "winsw\WinSW.NET461.exe"
    if (-not (Test-Path -LiteralPath $path)) { Copy-Item -LiteralPath $download -Destination $path }
    return $path
}

function Write-WinSwConfig {
    param(
        [string]$ServiceName,
        [string]$DisplayName,
        [string]$Executable,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [hashtable]$Environment
    )
    $serviceDir = Join-Path $ServiceRoot $ServiceName
    $logPath = Join-Path $LogRoot $ServiceName
    Ensure-Directory $serviceDir
    Ensure-Directory $logPath
    # Repair directories created by installer versions that did not propagate
    # their restricted ACL to the WinSW wrapper and configuration files.
    Set-RestrictedAcl -Path $serviceDir
    $wrapper = Join-Path $serviceDir "$ServiceName.exe"
    $xmlPath = Join-Path $serviceDir "$ServiceName.xml"
    $winsw = Get-WinSwPath
    Copy-Item -LiteralPath $winsw -Destination $wrapper -Force
    $xml = @(
        "<service>"
        "  <id>$(Escape-Xml $ServiceName)</id>"
        "  <name>$(Escape-Xml $DisplayName)</name>"
        "  <description>Tool Defect local development infrastructure.</description>"
        "  <executable>$(Escape-Xml $Executable)</executable>"
        "  <arguments>$(Escape-Xml $Arguments)</arguments>"
        "  <workingdirectory>$(Escape-Xml $WorkingDirectory)</workingdirectory>"
        "  <logpath>$(Escape-Xml $logPath)</logpath>"
        "  <serviceaccount>"
        "    <username>LocalSystem</username>"
        "  </serviceaccount>"
        "  <startmode>Automatic</startmode>"
        "  <stoptimeout>20sec</stoptimeout>"
        "  <onfailure action='restart' delay='10 sec' />"
        "  <log mode='roll' />"
    )
    foreach ($key in $Environment.Keys) {
        $xml += "  <env name='$(Escape-Xml $key)' value='$(Escape-Xml ([string]$Environment[$key]))' />"
    }
    $xml += "</service>"
    Set-Content -LiteralPath $xmlPath -Value $xml -Encoding UTF8
    Set-RestrictedAcl -Path $serviceDir
    return [pscustomobject]@{ Wrapper = $wrapper; Config = $xmlPath; Directory = $serviceDir }
}

function Install-WinSwService {
    param($WrapperRecord)
    Invoke-Checked -FilePath $WrapperRecord.Wrapper -Arguments @("install") -Label "install service $($WrapperRecord.Wrapper)" -WorkingDirectory $WrapperRecord.Directory
    $serviceName = Split-Path -Leaf $WrapperRecord.Directory
    $script:CreatedServiceEntries += @($ServiceDefinitions | Where-Object ServiceName -eq $serviceName)
}

function Start-And-WaitService {
    param($Definition)
    Start-Service -Name $Definition.ServiceName
    $deadline = (Get-Date).AddSeconds(60)
    do {
        $service = Get-Service -Name $Definition.ServiceName -ErrorAction SilentlyContinue
        if ($null -ne $service -and $service.Status -eq "Running") { break }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    $service = Get-Service -Name $Definition.ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $service -or $service.Status -ne "Running") {
        Stop-WithError "$($Definition.Label) service did not become Running: $($Definition.ServiceName)"
    }
}

function Wait-ForHttp {
    param([string]$Url, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { return }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    Stop-WithError "HTTP health check failed: $Url"
}

function Wait-ForErlangCookie {
    param(
        [string[]]$Paths,
        [int]$TimeoutSeconds = 90
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        foreach ($path in $Paths) {
            try {
                if (Test-Path -LiteralPath $path -PathType Leaf) {
                    return (Get-Item -LiteralPath $path -Force).FullName
                }
            } catch { }
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    Stop-WithError "RabbitMQ LocalSystem Erlang cookie was not found within $TimeoutSeconds seconds. Expected one of: $($Paths -join ', ')."
}

function Wait-ForPortClosed {
    param([int]$Port, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $listener) { return }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    Stop-WithError "Port $Port remained listening after service removal."
}

function Wait-ForServiceRemoved {
    param([string]$ServiceName, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $service) { return }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    Stop-WithError "Service registration still exists after uninstall: $ServiceName"
}

function Get-ExtractedRoot {
    param([string]$Root)
    $children = @(Get-ChildItem -LiteralPath $Root -Directory)
    if ($children.Count -eq 1) { return $children[0].FullName }
    return $Root
}

function Install-Postgres {
    param([hashtable]$Values, [hashtable]$Artifacts)
    $root = Join-Path $ServiceRoot "postgresql"
    $data = Join-Path $DataRoot "postgresql"
    $archive = $Artifacts.postgres
    Expand-ArchiveArtifact -ArchivePath $archive -Destination $root -Type "zip" | Out-Null
    $initdb = Find-FileUnder -Root $root -Name "initdb.exe"
    $pgctl = Find-FileUnder -Root $root -Name "pg_ctl.exe"
    $psql = Find-FileUnder -Root $root -Name "psql.exe"
    if (Test-Path -LiteralPath (Join-Path $data "PG_VERSION")) {
        Write-Info "Reusing the owned PostgreSQL data directory."
    } else {
        if (Test-Path -LiteralPath $data) {
            $children = @(Get-ChildItem -LiteralPath $data -Force)
            if ($children.Count -gt 0) { Stop-WithError "PostgreSQL data directory is non-empty but not initialized: $data" }
        } else {
            Ensure-Directory $data
        }
        $pw = Join-Path $ConfigRoot "postgres.password.tmp"
        Set-Content -LiteralPath $pw -Value $Values.TD_DATABASE_PASSWORD -Encoding ascii
        try {
            Invoke-Checked -FilePath $initdb -Arguments @("-D", $data, "-U", "tool_defect", "--pwfile=$pw", "--auth=scram-sha-256", "--encoding=UTF8", "--no-locale") -Label "initialize PostgreSQL"
        } finally {
            Remove-Item -LiteralPath $pw -Force -ErrorAction SilentlyContinue
        }
    }
    Invoke-Checked -FilePath $pgctl -Arguments @("register", "-N", "ToolDefect-PostgreSQL", "-D", $data, "-S", "auto") -Label "register PostgreSQL service"
    $script:CreatedServiceEntries += @($ServiceDefinitions | Where-Object Key -eq "postgres")
    Start-And-WaitService -Definition ($ServiceDefinitions | Where-Object Key -eq "postgres")
    $env:PGPASSWORD = $Values.TD_DATABASE_PASSWORD
    try {
        $dbResult = & $psql -h 127.0.0.1 -U tool_defect -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'tool_defect'" 2>$null
        if ($LASTEXITCODE -ne 0) { Stop-WithError "PostgreSQL database existence check failed." }
        if (($dbResult -join "").Trim() -ne "1") {
            Invoke-Checked -FilePath $psql -Arguments @("-h", "127.0.0.1", "-U", "tool_defect", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", "CREATE DATABASE tool_defect") -Label "create tool_defect database"
        }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

function Install-RabbitMq {
    param([hashtable]$Values, [hashtable]$Artifacts)
    $erlangRoot = Join-Path $ServiceRoot "erlang"
    $rabbitRoot = Join-Path $ServiceRoot "rabbitmq"
    Expand-ArchiveArtifact -ArchivePath $Artifacts.erlang -Destination $erlangRoot -Type "zip" | Out-Null
    Expand-ArchiveArtifact -ArchivePath $Artifacts.rabbitmq -Destination $rabbitRoot -Type "zip" | Out-Null
    $erlangHome = Find-ErlangHome -Root $erlangRoot
    $rabbit = Get-ChildItem -LiteralPath $rabbitRoot -Directory -Filter "rabbitmq_server-*" | Select-Object -First 1
    if ($null -eq $rabbit) { $rabbit = Get-Item -LiteralPath $rabbitRoot }
    $sbin = Join-Path $rabbit.FullName "sbin"
    $serverBat = Join-Path $sbin "rabbitmq-server.bat"
    $pluginsBat = Join-Path $sbin "rabbitmq-plugins.bat"
    $ctlBat = Join-Path $sbin "rabbitmqctl.bat"
    $serviceBat = Join-Path $sbin "rabbitmq-service.bat"
    foreach ($path in @($serverBat, $pluginsBat, $ctlBat, $serviceBat)) { if (-not (Test-Path -LiteralPath $path)) { Stop-WithError "RabbitMQ executable is missing: $path" } }
    $rabbitData = Join-Path $DataRoot "rabbitmq"
    Ensure-Directory $rabbitData
    $oldEnvironment = @{}
    foreach ($name in @("ERLANG_HOME", "RABBITMQ_BASE", "RABBITMQ_NODENAME", "RABBITMQ_SERVICENAME", "HOMEDRIVE", "HOMEPATH")) {
        $oldEnvironment[$name] = (Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue).Value
    }
    $env:ERLANG_HOME = $erlangHome
    $env:RABBITMQ_BASE = $rabbitData
    $env:RABBITMQ_NODENAME = "tool_defect@localhost"
    $env:RABBITMQ_SERVICENAME = "ToolDefect-RabbitMQ"
    try {
        Invoke-Checked -FilePath $pluginsBat -Arguments @("enable", "rabbitmq_management") -Label "enable RabbitMQ management plugin" -WorkingDirectory $sbin
        Invoke-Checked -FilePath $serviceBat -Arguments @("install") -Label "install RabbitMQ Windows service" -WorkingDirectory $sbin
        $script:CreatedServiceEntries += @($ServiceDefinitions | Where-Object Key -eq "rabbitmq")
        Start-And-WaitService -Definition ($ServiceDefinitions | Where-Object Key -eq "rabbitmq")
        $cookie = Wait-ForErlangCookie -Paths @(
            (Join-Path $env:SystemRoot ".erlang.cookie")
            (Join-Path $env:SystemRoot "System32\config\systemprofile\.erlang.cookie")
        )
        $cookieProfile = Split-Path -Parent $cookie
        $cookieDrive = [IO.Path]::GetPathRoot($cookieProfile)
        $env:HOMEDRIVE = $cookieDrive.TrimEnd("\")
        $env:HOMEPATH = $cookieProfile.Substring($cookieDrive.Length - 1)
        Wait-ForHttp -Url "http://127.0.0.1:15672/"
        Invoke-Checked -FilePath $ctlBat -Arguments @("await_startup", "-t", "60") -Label "wait for RabbitMQ" -WorkingDirectory $sbin
        $users = & $ctlBat list_users 2>$null
        if ($LASTEXITCODE -ne 0) { Stop-WithError "RabbitMQ user existence check failed." }
        if (($users -join "`n") -match "(?m)^tool_defect\s") {
            Invoke-Checked -FilePath $ctlBat -Arguments @("change_password", "tool_defect", $Values.TD_RABBITMQ_PASSWORD) -Label "update RabbitMQ user password" -WorkingDirectory $sbin
        } else {
            & $ctlBat add_user tool_defect $Values.TD_RABBITMQ_PASSWORD *> $null
            if ($LASTEXITCODE -ne 0) { Stop-WithError "RabbitMQ user creation failed." }
        }
        Invoke-Checked -FilePath $ctlBat -Arguments @("set_user_tags", "tool_defect", "management") -Label "configure RabbitMQ user" -WorkingDirectory $sbin
        Invoke-Checked -FilePath $ctlBat -Arguments @("set_permissions", "-p", "/", "tool_defect", ".*", ".*", ".*") -Label "configure RabbitMQ permissions" -WorkingDirectory $sbin
    } finally {
        foreach ($entry in $oldEnvironment.GetEnumerator()) {
            if ($null -eq $entry.Value) {
                Remove-Item -Path "Env:$($entry.Key)" -ErrorAction SilentlyContinue
            } else {
                Set-Item -Path "Env:$($entry.Key)" -Value ([string]$entry.Value)
            }
        }
    }
}

function Install-Minio {
    param([hashtable]$Values, [hashtable]$Artifacts)
    $root = Join-Path $ServiceRoot "minio"
    Ensure-Directory $root
    $exe = Join-Path $root "minio.exe"
    Copy-Item -LiteralPath $Artifacts.minio -Destination $exe -Force
    $data = Join-Path $DataRoot "minio"
    Ensure-Directory $data
    $record = Write-WinSwConfig -ServiceName "ToolDefect-MinIO" -DisplayName "Tool Defect MinIO" -Executable $exe -Arguments ("server `"{0}`" --console-address :9001" -f $data) -WorkingDirectory $root -Environment @{
        MINIO_ROOT_USER = $Values.TD_S3_ACCESS_KEY
        MINIO_ROOT_PASSWORD = $Values.TD_S3_SECRET_KEY
    }
    Install-WinSwService -WrapperRecord $record
    Start-And-WaitService -Definition ($ServiceDefinitions | Where-Object Key -eq "object-storage")
    Wait-ForHttp -Url "http://127.0.0.1:9000/minio/health/live"
}

function Install-MonitoringServices {
    param([hashtable]$Values, [hashtable]$Artifacts)
    $otelRoot = Join-Path $ServiceRoot "otel"
    $promRoot = Join-Path $ServiceRoot "prometheus"
    $grafanaRoot = Join-Path $ServiceRoot "grafana"
    $lokiRoot = Join-Path $ServiceRoot "loki"
    $tempoRoot = Join-Path $ServiceRoot "tempo"
    Expand-ArchiveArtifact -ArchivePath $Artifacts.otel -Destination $otelRoot -Type "tar.gz" | Out-Null
    Expand-ArchiveArtifact -ArchivePath $Artifacts.prometheus -Destination $promRoot -Type "zip" | Out-Null
    Expand-ArchiveArtifact -ArchivePath $Artifacts.grafana -Destination $grafanaRoot -Type "zip" | Out-Null
    Expand-ArchiveArtifact -ArchivePath $Artifacts.loki -Destination $lokiRoot -Type "zip" | Out-Null
    Expand-ArchiveArtifact -ArchivePath $Artifacts.tempo -Destination $tempoRoot -Type "tar.gz" | Out-Null
    $otelExe = Find-FileUnder -Root $otelRoot -Name "otelcol-contrib.exe"
    $promExe = Find-FileUnder -Root $promRoot -Name "prometheus.exe"
    $grafanaExe = Find-FileUnder -Root $grafanaRoot -Name "grafana-server.exe"
    $lokiExe = Find-FileUnder -Root $lokiRoot -Name "loki-windows-amd64.exe"
    $tempoExe = Find-FileUnder -Root $tempoRoot -Name "tempo.exe"

    $promData = Join-Path $DataRoot "prometheus"
    $grafanaData = Join-Path $DataRoot "grafana"
    $lokiData = Join-Path $DataRoot "loki"
    $tempoData = Join-Path $DataRoot "tempo"
    Ensure-Directory $promData
    Ensure-Directory $grafanaData
    Ensure-Directory $lokiData
    Ensure-Directory $tempoData
    $grafanaProvisioning = Join-Path $ConfigRoot "grafana\provisioning"
    $grafanaHome = Split-Path -Parent (Split-Path -Parent $grafanaExe)

    $otelRecord = Write-WinSwConfig -ServiceName "ToolDefect-OTel" -DisplayName "Tool Defect OpenTelemetry Collector" -Executable $otelExe -Arguments ("--config=`"{0}`"" -f (Join-Path $ConfigRoot "otel-collector.yml")) -WorkingDirectory (Split-Path -Parent $otelExe) -Environment @{}
    Install-WinSwService -WrapperRecord $otelRecord
    $promRecord = Write-WinSwConfig -ServiceName "ToolDefect-Prometheus" -DisplayName "Tool Defect Prometheus" -Executable $promExe -Arguments ("--config.file=`"{0}`" --storage.tsdb.path=`"{1}`"" -f (Join-Path $ConfigRoot "prometheus\prometheus.yml"), $promData) -WorkingDirectory (Split-Path -Parent $promExe) -Environment @{}
    Install-WinSwService -WrapperRecord $promRecord
    $grafanaRecord = Write-WinSwConfig -ServiceName "ToolDefect-Grafana" -DisplayName "Tool Defect Grafana" -Executable $grafanaExe -Arguments ("--config=`"{0}`"" -f (Join-Path $grafanaHome "conf\defaults.ini")) -WorkingDirectory $grafanaHome -Environment @{
        GF_PATHS_HOME = $grafanaHome
        GF_PATHS_CONFIG = Join-Path $grafanaHome "conf\defaults.ini"
        GF_PATHS_DATA = $grafanaData
        GF_PATHS_PROVISIONING = $grafanaProvisioning
        GF_SECURITY_ADMIN_USER = $Values.TD_GRAFANA_ADMIN_USER
        GF_SECURITY_ADMIN_PASSWORD = $Values.TD_GRAFANA_ADMIN_PASSWORD
        GF_USERS_ALLOW_SIGN_UP = "false"
    }
    Install-WinSwService -WrapperRecord $grafanaRecord
    $lokiRecord = Write-WinSwConfig -ServiceName "ToolDefect-Loki" -DisplayName "Tool Defect Loki" -Executable $lokiExe -Arguments ("-config.file=`"{0}`"" -f (Join-Path $ConfigRoot "loki.yml")) -WorkingDirectory (Split-Path -Parent $lokiExe) -Environment @{}
    Install-WinSwService -WrapperRecord $lokiRecord
    $tempoRecord = Write-WinSwConfig -ServiceName "ToolDefect-Tempo" -DisplayName "Tool Defect Tempo" -Executable $tempoExe -Arguments ("-config.file=`"{0}`"" -f (Join-Path $ConfigRoot "tempo.yml")) -WorkingDirectory (Split-Path -Parent $tempoExe) -Environment @{}
    Install-WinSwService -WrapperRecord $tempoRecord

    foreach ($definition in @("telemetry", "prometheus", "grafana", "loki", "tempo")) {
        Start-And-WaitService -Definition ($ServiceDefinitions | Where-Object Key -eq $definition)
    }
    Wait-ForHttp -Url "http://127.0.0.1:9090/-/ready"
    Wait-ForHttp -Url "http://127.0.0.1:3000/api/health"
    Wait-ForHttp -Url "http://127.0.0.1:3100/ready"
    Wait-ForHttp -Url "http://127.0.0.1:3200/ready"
}

function New-State {
    param([hashtable]$Values, [hashtable]$ArtifactPaths)
    $services = @($ServiceDefinitions | ForEach-Object {
        [ordered]@{ Key = $_.Key; ServiceName = $_.ServiceName; Label = $_.Label; Port = $_.Port; HealthUrl = $_.HealthUrl; Kind = $_.Kind }
    })
    $artifacts = @($ArtifactDefinitions | ForEach-Object {
        [ordered]@{ Key = $_.Key; Version = $_.Version; FileName = $_.FileName; Sha256 = (Get-FileHash -LiteralPath $ArtifactPaths[$_.Key] -Algorithm SHA256).Hash; Path = $ArtifactPaths[$_.Key] }
    })
    return [ordered]@{
        SchemaVersion = $StateVersion
        State = "installed"
        ManagedBy = "setup-windows-infrastructure.ps1"
        ProjectRoot = $ProjectRoot
        InstallRoot = $InstallRoot
        EnvFile = $EnvFile
        Services = $services
        Artifacts = $artifacts
        DataRoot = $DataRoot
        ConfigRoot = $ConfigRoot
        CreatedAtUtc = [DateTime]::UtcNow.ToString("o")
    }
}

function Write-State {
    param($State)
    Ensure-Directory $InstallRoot
    $temporary = "$StatePath.partial"
    try {
        $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Set-RestrictedAcl -Path $temporary
        Move-Item -LiteralPath $temporary -Destination $StatePath -Force
    } catch {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Test-PartialInstallation {
    if (-not (Test-Path -LiteralPath $PartialStatePath -PathType Leaf)) { return $false }
    try {
        $partial = Get-Content -LiteralPath $PartialStatePath -Raw | ConvertFrom-Json
    } catch {
        Stop-WithError "Partial installation marker is invalid: $PartialStatePath"
    }
    if ($partial.ManagedBy -ne "setup-windows-infrastructure.ps1" -or [int]$partial.SchemaVersion -ne $StateVersion) {
        Stop-WithError "Partial installation marker is not owned by this installer: $PartialStatePath"
    }
    if ([IO.Path]::GetFullPath([string]$partial.ProjectRoot) -ne $ProjectRoot -or
        [IO.Path]::GetFullPath([string]$partial.InstallRoot) -ne $InstallRoot -or
        [IO.Path]::GetFullPath([string]$partial.EnvFile) -ne $EnvFile) {
        Stop-WithError "Partial installation marker belongs to a different project or install root: $PartialStatePath"
    }
    return $true
}

function Write-PartialInstallation {
    Ensure-Directory $InstallRoot
    $partial = [ordered]@{
        SchemaVersion = $StateVersion
        State = "installing"
        ManagedBy = "setup-windows-infrastructure.ps1"
        ProjectRoot = $ProjectRoot
        InstallRoot = $InstallRoot
        EnvFile = $EnvFile
        CreatedAtUtc = [DateTime]::UtcNow.ToString("o")
    }
    $partial | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PartialStatePath -Encoding UTF8
}

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        Stop-WithError "Installation state does not exist: $StatePath"
    }
    try { $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json } catch { Stop-WithError "Installation state is invalid: $StatePath" }
    if ($state.ManagedBy -ne "setup-windows-infrastructure.ps1" -or [int]$state.SchemaVersion -ne $StateVersion) {
        Stop-WithError "Installation state is not owned by this installer: $StatePath"
    }
    $allowedNames = @($ServiceDefinitions | ForEach-Object ServiceName)
    foreach ($entry in @($state.Services)) {
        if ($entry.ServiceName -notin $allowedNames) {
            Stop-WithError "Installation state contains an unmanaged service: $($entry.ServiceName)"
        }
    }
    return $state
}

function Show-Status {
    Ensure-WindowsRuntime
    if (-not (Test-Path -LiteralPath $StatePath)) {
        Write-Host "NOT_INSTALLED"
        exit 1
    }
    $state = Read-State
    Write-Host "State: $($state.State)"
    Write-Host "InstallRoot: $($state.InstallRoot)"
    Write-Host "Environment: $($state.EnvFile)"
    Write-Host ("{0,-24} {1,-10} {2,-10} {3}" -f "Component", "Service", "Port", "Health")
    $failed = $false
    foreach ($entry in $state.Services) {
        $definition = $ServiceDefinitions | Where-Object Key -eq $entry.Key | Select-Object -First 1
        $healthUrl = if ($entry.HealthUrl) { [string]$entry.HealthUrl } elseif ($definition) { [string]$definition.HealthUrl } else { $null }
        $service = Get-Service -Name $entry.ServiceName -ErrorAction SilentlyContinue
        $status = if ($null -eq $service) { "MISSING" } else { [string]$service.Status }
        $listener = Get-NetTCPConnection -State Listen -LocalPort ([int]$entry.Port) -ErrorAction SilentlyContinue | Select-Object -First 1
        $port = if ($null -eq $listener) { "CLOSED" } else { "LISTENING" }
        $health = "N/A"
        if ($healthUrl) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 5
                $health = if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { "HEALTHY" } else { "FAILED" }
            } catch { $health = "FAILED" }
        }
        Write-Host ("{0,-24} {1,-10} {2,-10} {3}" -f $entry.Label, $status, $port, $health)
        if ($status -ne "Running" -or $port -ne "LISTENING" -or $health -eq "FAILED") { $failed = $true }
    }
    if ($failed) { exit 1 }
}

function Remove-ManagedService {
    param($Entry)
    $service = Get-Service -Name $Entry.ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $service) { return }
    if ($service.Status -ne "Stopped") {
        Stop-Service -Name $Entry.ServiceName -Force
        $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
    }
    if ($Entry.Kind -eq "postgres") {
        $pgctl = Get-ChildItem -LiteralPath (Join-Path $ServiceRoot "postgresql") -Recurse -File -Filter "pg_ctl.exe" | Select-Object -First 1
        if ($null -ne $pgctl) {
            & $pgctl.FullName unregister -N $Entry.ServiceName *> $null
            if ($LASTEXITCODE -ne 0) { Stop-WithError "Could not unregister PostgreSQL service: $($Entry.ServiceName)" }
        }
    } elseif ($Entry.Kind -eq "rabbitmq") {
        $serviceBat = Get-ChildItem -LiteralPath (Join-Path $ServiceRoot "rabbitmq") -Recurse -File -Filter "rabbitmq-service.bat" | Select-Object -First 1
        if ($null -ne $serviceBat) {
            $erlangHome = Find-ErlangHome -Root (Join-Path $ServiceRoot "erlang")
            $oldEnvironment = @{}
            foreach ($name in @("ERLANG_HOME", "RABBITMQ_BASE", "RABBITMQ_SERVICENAME")) {
                $oldEnvironment[$name] = (Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue).Value
            }
            $env:RABBITMQ_SERVICENAME = $Entry.ServiceName
            $env:RABBITMQ_BASE = Join-Path $DataRoot "rabbitmq"
            $env:ERLANG_HOME = $erlangHome
            try {
                & $serviceBat.FullName remove *> $null
                if ($LASTEXITCODE -ne 0) { Stop-WithError "Could not remove RabbitMQ service: $($Entry.ServiceName)" }
            } finally {
                foreach ($environmentEntry in $oldEnvironment.GetEnumerator()) {
                    if ($null -eq $environmentEntry.Value) {
                        Remove-Item -Path "Env:$($environmentEntry.Key)" -ErrorAction SilentlyContinue
                    } else {
                        Set-Item -Path "Env:$($environmentEntry.Key)" -Value ([string]$environmentEntry.Value)
                    }
                }
            }
        }
    } else {
        $wrapper = Join-Path $ServiceRoot "$($Entry.ServiceName)\$($Entry.ServiceName).exe"
        if (-not (Test-Path -LiteralPath $wrapper)) { $wrapper = Get-ChildItem -LiteralPath $ServiceRoot -Recurse -File -Filter "$($Entry.ServiceName).exe" | Select-Object -ExpandProperty FullName -First 1 }
        if ($wrapper) {
            & $wrapper uninstall *> $null
            if ($LASTEXITCODE -ne 0) { Stop-WithError "Could not uninstall WinSW service: $($Entry.ServiceName)" }
        }
    }
    Wait-ForServiceRemoved -ServiceName $Entry.ServiceName
    $portsToClose = @([int]$Entry.Port)
    if ($Entry.Kind -eq "rabbitmq") { $portsToClose += 15672 }
    foreach ($port in $portsToClose) {
        Wait-ForPortClosed -Port $port
    }
}

function Cleanup-CreatedServices {
    foreach ($entry in @($script:CreatedServiceEntries | Select-Object -Unique | Sort-Object Key -Descending)) {
        try { Remove-ManagedService -Entry $entry } catch { Write-Warn "Could not clean up service $($entry.ServiceName): $($_.Exception.Message)" }
    }
    $script:CreatedServiceEntries = @()
}

function Uninstall-Infrastructure {
    Ensure-Administrator
    Ensure-WindowsRuntime
    $state = Read-State
    foreach ($entry in @($state.Services | Sort-Object Key -Descending)) { Remove-ManagedService -Entry $entry }
    $state.State = "uninstalled"
    $state.UninstalledAtUtc = [DateTime]::UtcNow.ToString("o")
    Write-State -State $state
    Write-Host "Services uninstalled. Data, downloads, configuration and credentials were preserved." -ForegroundColor Green
}

function Show-Help {
    @"
Native Windows infrastructure installer for local development only.

Usage:
  .\tools\dev\setup-windows-infrastructure.ps1 -Action install
  .\tools\dev\setup-windows-infrastructure.ps1 -Action status
  .\tools\dev\setup-windows-infrastructure.ps1 -Action uninstall
  .\tools\dev\setup-windows-infrastructure.ps1 -Action help

Optional:
  -InstallRoot <path>  Override .build\windows-infrastructure.
  -EnvFile <path>      Override .windows.env.ps1.
  -StartAt <stage>     Resume at postgres, rabbitmq, minio or monitoring; earlier services must be healthy.
  -SkipDownloads       Use only existing verified download cache entries.
  -ResumePartial       Explicitly adopt a prior incomplete run with no installer marker.
  -WhatIf              Show planned changes without modifying the machine.

The installer uses no Docker or WSL. It installs PostgreSQL, RabbitMQ,
MinIO, OpenTelemetry Collector, Prometheus, Grafana, Loki and Tempo.
MinIO on Windows is for local development/evaluation, not production.
Existing services, ports and unmanaged data directories are never adopted.
Run install/uninstall from an elevated PowerShell prompt.
"@ | Write-Host
}

function Install-Infrastructure {
    Ensure-Administrator
    if ($StartAt -ne "none") {
        Write-Info "Resuming from $StartAt; earlier components must already be healthy."
    }
    $ownedInstallation = $false
    $partialInstallation = Test-PartialInstallation
    if (Test-Path -LiteralPath $StatePath) {
        $oldState = Read-State
        if ($oldState.State -ne "uninstalled") {
            Stop-WithError "An installation state already exists. Use -Action status or uninstall first."
        }
        if ([IO.Path]::GetFullPath([string]$oldState.InstallRoot) -ne $InstallRoot) {
            Stop-WithError "The existing installation state belongs to a different install root: $($oldState.InstallRoot)"
        }
        $ownedInstallation = $true
    } elseif ($partialInstallation) {
        $ownedInstallation = $true
    } elseif ($ResumePartial) {
        Write-Warn "Explicitly resuming an incomplete installation under $InstallRoot. Verify that its contents were created by this installer."
        $ownedInstallation = $true
    }
    Test-ServiceConflict -ResumeOwnedServices:($partialInstallation -or $ResumePartial)
    Test-InstallationDirectoryConflict -OwnedInstallation:$ownedInstallation
    Ensure-Directory $InstallRoot
    Ensure-Directory $PackageRoot
    Ensure-Directory $ServiceRoot
    Ensure-Directory $DataRoot
    Ensure-Directory $ConfigRoot
    Ensure-Directory $LogRoot
    if (-not $partialInstallation) {
        Write-PartialInstallation
    }

    $existing = Read-GeneratedEnvironment -Path $EnvFile
    $createdEnv = $false
    if ($null -eq $existing) {
        $postgresDataInitialized = Test-Path -LiteralPath (Join-Path $DataRoot "postgresql\PG_VERSION")
        if ($ownedInstallation -and $postgresDataInitialized) {
            Stop-WithError "Owned installation credentials are missing: $EnvFile. Refusing to generate replacement credentials for preserved data."
        }
        $values = New-EnvironmentValues
        $createdEnv = $true
    } else {
        $values = Get-EnvironmentValues -Existing $existing
    }
    if ($createdEnv) {
        Write-EnvironmentFile -Values $values -CreatedByThisRun
    }

    $artifactPaths = @{}
    try {
        foreach ($artifact in $ArtifactDefinitions) {
            if ($SkipDownloads) {
                $artifactPaths[$artifact.Key] = Use-CachedArtifact -Artifact $artifact
            } else {
                $artifactPaths[$artifact.Key] = Download-Artifact -Artifact $artifact
            }
        }
        Write-NativeConfigs -Values $values
        if (Should-InstallStage "postgres") {
            Install-Postgres -Values $values -Artifacts $artifactPaths
        }
        if (Should-InstallStage "rabbitmq") {
            Install-RabbitMq -Values $values -Artifacts $artifactPaths
        }
        if (Should-InstallStage "minio") {
            Install-Minio -Values $values -Artifacts $artifactPaths
        }
        if (Should-InstallStage "monitoring") {
            Install-MonitoringServices -Values $values -Artifacts $artifactPaths
        }
        $state = New-State -Values $values -ArtifactPaths $artifactPaths
        Set-RestrictedAcl -Path $InstallRoot
        Write-State -State $state
        Remove-Item -LiteralPath $PartialStatePath -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Native infrastructure installed and healthy." -ForegroundColor Green
        Write-Host "Environment file: $EnvFile" -ForegroundColor DarkGray
    } catch {
        Write-Warn "Installation failed. Cleaning up service registrations created by this invocation; data, credentials and download cache are preserved."
        Cleanup-CreatedServices
        throw
    }
}

try {
    Set-Location $ProjectRoot
    if ($Action -eq "help") { Show-Help; exit 0 }
    if ($Action -eq "status") { Show-Status; exit 0 }
    if ($WhatIfPreference) {
        Write-Host "WhatIf: would install/manage native Windows infrastructure under $InstallRoot." -ForegroundColor Yellow
        Write-Host "WhatIf: no downloads, services, credentials or configuration files will be changed." -ForegroundColor Yellow
        exit 0
    }
    switch ($Action) {
        "install" { Install-Infrastructure }
        "uninstall" { Uninstall-Infrastructure }
    }
} catch {
    if ($_.Exception.Message.StartsWith("[WINDOWS-INFRA-FAILED]", [StringComparison]::Ordinal)) {
        Write-Error $_.Exception.Message
    } else {
        Write-Error "[WINDOWS-INFRA-FAILED] $($_.Exception.Message)"
    }
    exit 1
}
