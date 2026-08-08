#Requires -Version 5.1
<#
.SYNOPSIS
    Run the native Windows development stack without Docker or WSL.

.DESCRIPTION
    The script mirrors tools/dev/start-all.sh at the orchestration level.
    PostgreSQL, RabbitMQ, object storage, telemetry, Prometheus, Grafana,
    Loki, and Tempo must already be registered as Windows services. The
    script starts and stops only services that it started itself.
#>

param(
    [ValidateSet("start", "stop", "status", "logs", "help")]
    [string]$Action = "start",
    [string]$EnvFile,
    [switch]$Detach,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$RuntimeRoot = Join-Path $ProjectRoot ".build\windows-runtime"
$ServiceOwnershipPath = Join-Path $RuntimeRoot "services.started.json"
$StopRequestPath = Join-Path $RuntimeRoot "stop.requested"
$RequiredNodeVersion = "20.13.1"
$RequiredPnpmVersion = "10.34.5"
$NodeHome = Join-Path $ProjectRoot ".build\toolchains\node-v$RequiredNodeVersion-win-x64"
$CorepackHome = Join-Path $ProjectRoot ".build\toolchains\corepack"
$PnpmHome = Join-Path $ProjectRoot ".build\toolchains\pnpm"
$NativeTempHome = Join-Path $ProjectRoot ".build\toolchains\tmp"
$NativeInfrastructureRoot = Join-Path $ProjectRoot ".build\windows-infrastructure"
$BackendRoot = Join-Path $ProjectRoot "services\business-api"
$WebRoot = Join-Path $ProjectRoot "apps\web-console"
$BackendWrapper = Join-Path $BackendRoot "mvnw.cmd"
$FrontendLogRoot = Join-Path $RuntimeRoot "web-console"
$BackendLogRoot = Join-Path $RuntimeRoot "business-api"

$ServiceDefinitions = @(
    [pscustomobject]@{
        Key = "postgres"
        Label = "PostgreSQL"
        EnvName = "TD_WINDOWS_POSTGRES_SERVICE"
        Port = 5432
        HealthUrl = $null
    }
    [pscustomobject]@{
        Key = "rabbitmq"
        Label = "RabbitMQ"
        EnvName = "TD_WINDOWS_RABBITMQ_SERVICE"
        Port = 5672
        HealthUrl = $null
    }
    [pscustomobject]@{
        Key = "object-storage"
        Label = "Object storage"
        EnvName = "TD_WINDOWS_OBJECT_STORAGE_SERVICE"
        Port = 9000
        HealthUrl = "http://127.0.0.1:9000/minio/health/live"
    }
    [pscustomobject]@{
        Key = "telemetry"
        Label = "OpenTelemetry collector"
        EnvName = "TD_WINDOWS_OTEL_SERVICE"
        Port = 4317
        HealthUrl = $null
    }
    [pscustomobject]@{
        Key = "prometheus"
        Label = "Prometheus"
        EnvName = "TD_WINDOWS_PROMETHEUS_SERVICE"
        Port = 9090
        HealthUrl = "http://127.0.0.1:9090/-/ready"
    }
    [pscustomobject]@{
        Key = "grafana"
        Label = "Grafana"
        EnvName = "TD_WINDOWS_GRAFANA_SERVICE"
        Port = 3000
        HealthUrl = "http://127.0.0.1:3000/api/health"
    }
    [pscustomobject]@{
        Key = "loki"
        Label = "Loki"
        EnvName = "TD_WINDOWS_LOKI_SERVICE"
        Port = 3100
        HealthUrl = "http://127.0.0.1:3100/ready"
    }
    [pscustomobject]@{
        Key = "tempo"
        Label = "Tempo"
        EnvName = "TD_WINDOWS_TEMPO_SERVICE"
        Port = 3200
        HealthUrl = "http://127.0.0.1:3200/ready"
    }
)

$script:ServiceOwnership = @()
$script:StartedProcessNames = @()
$script:StartInProgress = $false

function Stop-WithError {
    param([string]$Message)
    throw "[WINDOWS-RUN-FAILED] $Message"
}

function Get-CommandPath {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Get-EnvValue {
    param([string]$Name)
    return [Environment]::GetEnvironmentVariable($Name, "Process")
}

function Set-DefaultEnvValue {
    param([string]$Name, [string]$Value)
    if ([string]::IsNullOrWhiteSpace((Get-EnvValue -Name $Name))) {
        Set-Item -Path "Env:$Name" -Value $Value
    }
}

function Require-EnvValue {
    param([string]$Name)
    $value = Get-EnvValue -Name $Name
    if ([string]::IsNullOrWhiteSpace($value)) {
        Stop-WithError "Required environment variable is missing: $Name"
    }
    return $value
}

function Resolve-ProjectPath {
    param([string]$Path, [switch]$MustExist)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        Stop-WithError "A path argument is empty."
    }
    $candidate = $Path
    if (-not [IO.Path]::IsPathRooted($Path)) {
        $candidate = Join-Path $ProjectRoot $Path
    }
    if ($MustExist -and -not (Test-Path -LiteralPath $candidate)) {
        Stop-WithError "Path does not exist: $candidate"
    }
    return [IO.Path]::GetFullPath($candidate)
}

function Load-Environment {
    $path = $EnvFile
    if (-not $path) {
        $path = Get-EnvValue -Name "TOOL_DEFECT_ENV_FILE"
    }
    if (-not $path) {
        $path = Join-Path $ProjectRoot ".windows.env.ps1"
    }
    $resolved = Resolve-ProjectPath -Path $path -MustExist
    Write-Host "[run] Loading environment: $resolved" -ForegroundColor DarkGray
    & $resolved
}

function Ensure-Configuration {
    Set-DefaultEnvValue -Name "TD_MANAGEMENT_PORT" -Value "9091"
    Set-DefaultEnvValue -Name "TD_ENVIRONMENT" -Value "development"
    Set-DefaultEnvValue -Name "TD_SERVICE_VERSION" -Value "workspace"
    Set-DefaultEnvValue -Name "TD_AUTH_SECURE_COOKIE" -Value "false"
    Set-DefaultEnvValue -Name "TD_RABBITMQ_SSL_ENABLED" -Value "false"
    Set-DefaultEnvValue -Name "TD_S3_REQUIRE_TLS" -Value "false"

    foreach ($name in @(
        "TD_DATABASE_URL",
        "TD_DATABASE_USERNAME",
        "TD_DATABASE_PASSWORD",
        "TD_RABBITMQ_ADDRESSES",
        "TD_RABBITMQ_USERNAME",
        "TD_RABBITMQ_PASSWORD",
        "TD_S3_ENDPOINT",
        "TD_S3_ACCESS_KEY",
        "TD_S3_SECRET_KEY",
        "TD_MESSAGING_ENABLED",
        "TD_STORAGE_ENABLED",
        "TD_OPERATIONS_ENABLED"
    )) {
        Require-EnvValue -Name $name | Out-Null
    }

    foreach ($name in @("TD_MESSAGING_ENABLED", "TD_STORAGE_ENABLED", "TD_OPERATIONS_ENABLED")) {
        if ((Get-EnvValue -Name $name) -notmatch "^(?i:true)$") {
            Stop-WithError "$name must be true for the native start action."
        }
    }

    foreach ($name in @(
        "TD_BOOTSTRAP_ADMIN_USERNAME",
        "TD_BOOTSTRAP_ADMIN_DISPLAY_NAME",
        "TD_BOOTSTRAP_ADMIN_PASSWORD_FILE"
    )) {
        if (-not [string]::IsNullOrWhiteSpace((Get-EnvValue -Name $name))) {
            Stop-WithError "$name must not be configured for the Windows runner; first-account setup is interactive."
        }
    }

    foreach ($definition in $ServiceDefinitions) {
        $serviceName = Require-EnvValue -Name $definition.EnvName
        $definition | Add-Member -NotePropertyName ServiceName -NotePropertyValue $serviceName -Force
    }

    if (-not (Test-Path -LiteralPath $BackendWrapper)) {
        Stop-WithError "Maven Wrapper is missing: $BackendWrapper"
    }
    if (-not (Test-Path -LiteralPath $WebRoot)) {
        Stop-WithError "Web console directory is missing: $WebRoot"
    }
}

function Clear-InitialAdminEnvironment {
    foreach ($name in @(
        "TD_BOOTSTRAP_ADMIN_USERNAME",
        "TD_BOOTSTRAP_ADMIN_DISPLAY_NAME",
        "TD_BOOTSTRAP_ADMIN_PASSWORD_FILE"
    )) {
        if (Test-Path -Path "Env:$name") {
            Remove-Item -Path "Env:$name" -Force -ErrorAction Stop
        }
    }
}

function Set-RestrictedFileAcl {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
    $identityName = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $systemSid = New-Object Security.Principal.SecurityIdentifier -ArgumentList @("S-1-5-18")
    $administratorsSid = New-Object Security.Principal.SecurityIdentifier -ArgumentList @("S-1-5-32-544")
    foreach ($identity in @($identityName, $systemSid, $administratorsSid)) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule -ArgumentList @(
            $identity, "FullControl", "Allow"
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Value
    )
    [IO.File]::WriteAllText($Path, $Value, [Text.UTF8Encoding]::new($false))
}

function Get-PostgresClientPath {
    $configured = Get-CommandPath -Name "psql.exe"
    if ($configured) { return $configured }

    $postgresRoot = Join-Path $NativeInfrastructureRoot "services\postgresql"
    if (Test-Path -LiteralPath $postgresRoot) {
        $candidate = Get-ChildItem -LiteralPath $postgresRoot -File -Filter "psql.exe" -Recurse `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    Stop-WithError "PostgreSQL client psql.exe is required to inspect local account state."
}

function Get-PostgresConnectionInfo {
    $url = Require-EnvValue -Name "TD_DATABASE_URL"
    $match = [regex]::Match(
        $url,
        '^jdbc:postgresql://(?<host>\[[^\]]+\]|[^/:]+)(?::(?<port>\d+))?/(?<database>[^?]+)(?:\?.*)?$'
    )
    if (-not $match.Success) {
        Stop-WithError "TD_DATABASE_URL must be a PostgreSQL JDBC URL that the Windows runner can inspect."
    }

    $hostName = $match.Groups["host"].Value
    if ($hostName.StartsWith("[") -and $hostName.EndsWith("]")) {
        $hostName = $hostName.Substring(1, $hostName.Length - 2)
    }
    $database = [Uri]::UnescapeDataString($match.Groups["database"].Value)
    if ([string]::IsNullOrWhiteSpace($database)) {
        Stop-WithError "TD_DATABASE_URL does not contain a database name."
    }

    return [pscustomobject]@{
        Host = $hostName
        Port = if ($match.Groups["port"].Success) {
            [int]$match.Groups["port"].Value
        } else {
            5432
        }
        Database = $database
        Username = Require-EnvValue -Name "TD_DATABASE_USERNAME"
        Password = Require-EnvValue -Name "TD_DATABASE_PASSWORD"
    }
}

function Get-LocalCredentialCount {
    $psql = Get-PostgresClientPath
    $connection = Get-PostgresConnectionInfo
    $arguments = @(
        "-X", "-w", "-q",
        "-h", $connection.Host,
        "-p", [string]$connection.Port,
        "-U", $connection.Username,
        "-d", $connection.Database,
        "-At",
        "-v", "ON_ERROR_STOP=1",
        "-c", "SELECT count(*) FROM sys_user_credential;"
    )
    $previousPassword = [Environment]::GetEnvironmentVariable("PGPASSWORD", "Process")
    Set-Item -Path "Env:PGPASSWORD" -Value $connection.Password
    try {
        $output = & $psql @arguments 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            $detail = (($output | ForEach-Object { [string]$_ }) -join " ").Trim()
            if ([string]::IsNullOrWhiteSpace($detail)) { $detail = "no diagnostic output" }
            Stop-WithError "Could not inspect local account state with psql: $detail"
        }
        $countLine = @($output |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { $_ -match '^\d+$' } |
            Select-Object -Last 1)
        if ($countLine.Count -ne 1) {
            Stop-WithError "PostgreSQL account-state query returned an invalid result."
        }
        return [int]$countLine[0]
    } finally {
        if ($null -eq $previousPassword) {
            if (Test-Path -Path "Env:PGPASSWORD") {
                Remove-Item -Path "Env:PGPASSWORD" -Force -ErrorAction Stop
            }
        } else {
            Set-Item -Path "Env:PGPASSWORD" -Value $previousPassword
        }
    }
}

function Wait-ForLocalCredential {
    param([int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $count = Get-LocalCredentialCount
        if ($count -gt 0) { return $count }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    Stop-WithError "Initial administrator bootstrap did not create a local account within $TimeoutSeconds seconds."
}

function ConvertFrom-SecureStringPlainText {
    param([Security.SecureString]$Value)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Read-InitialAdminInput {
    while ($true) {
        $username = Read-Host "Initial administrator username [admin]"
        if ([string]::IsNullOrWhiteSpace($username)) { $username = "admin" }
        $username = $username.Trim().ToLowerInvariant()
        if ($username -notmatch '^[a-z0-9][a-z0-9._-]{2,63}$') {
            Write-Warning "Username must match ^[a-z0-9][a-z0-9._-]{2,63}$."
            continue
        }
        break
    }
    $defaultDisplayName = [string]::Concat(
        [char]0x7cfb, [char]0x7edf, [char]0x7ba1, [char]0x7406, [char]0x5458
    )
    $displayName = Read-Host ("Initial administrator display name [{0}]" -f $defaultDisplayName)
    if ([string]::IsNullOrWhiteSpace($displayName)) { $displayName = $defaultDisplayName }
    $displayName = $displayName.Trim()
    if ([string]::IsNullOrWhiteSpace($displayName)) {
        Stop-WithError "Initial administrator display name must not be blank."
    }
    if ($displayName.Length -gt 256) {
        Stop-WithError "Initial administrator display name must be at most 256 characters."
    }

    while ($true) {
        $firstSecure = $null
        $secondSecure = $null
        $firstPlain = $null
        $secondPlain = $null
        try {
            $firstSecure = Read-Host "Initial administrator password (hidden)" -AsSecureString
            $secondSecure = Read-Host "Confirm initial administrator password (hidden)" -AsSecureString
            $firstPlain = ConvertFrom-SecureStringPlainText -Value $firstSecure
            $secondPlain = ConvertFrom-SecureStringPlainText -Value $secondSecure
            if ($firstPlain -cne $secondPlain) {
                Write-Warning "The two passwords do not match."
                continue
            }
            if ($firstPlain.Length -lt 12 -or $firstPlain.Length -gt 128) {
                Write-Warning "Password length must be between 12 and 128 characters."
                continue
            }
            if ($firstPlain -ieq $username) {
                Write-Warning "Password must not equal the username."
                continue
            }
            return [pscustomobject]@{
                Username = $username
                DisplayName = $displayName
                Password = $firstPlain
            }
        } finally {
            if ($firstSecure) { $firstSecure.Dispose() }
            if ($secondSecure) { $secondSecure.Dispose() }
        }
    }
}

function Initialize-LocalAdminIfRequired {
    $credentialCount = Get-LocalCredentialCount
    if ($credentialCount -gt 0) {
        Write-Host "[run] Local account already exists; skipping first-account setup." -ForegroundColor DarkGray
        return
    }

    Write-Host "No local account exists. Configure the initial administrator now." -ForegroundColor Cyan
    $initialAdmin = Read-InitialAdminInput
    $passwordPath = Join-Path $RuntimeRoot "bootstrap-admin.password"
    try {
        Stop-ManagedProcess -Name "business-api"
        if (Test-Path -LiteralPath $passwordPath) {
            Remove-Item -LiteralPath $passwordPath -Force -ErrorAction Stop
        }
        Write-Utf8NoBomFile -Path $passwordPath -Value $initialAdmin.Password
        Set-RestrictedFileAcl -Path $passwordPath
        Set-Item -Path "Env:TD_BOOTSTRAP_ADMIN_USERNAME" -Value $initialAdmin.Username
        Set-Item -Path "Env:TD_BOOTSTRAP_ADMIN_DISPLAY_NAME" -Value $initialAdmin.DisplayName
        Set-Item -Path "Env:TD_BOOTSTRAP_ADMIN_PASSWORD_FILE" -Value $passwordPath
        Start-Backend

        Wait-ForLocalCredential | Out-Null
        Write-Host "[OK] Initial administrator created. The first login must change its password." -ForegroundColor Green
    } finally {
        $cleanupError = $null
        try {
            Clear-InitialAdminEnvironment
        } catch {
            $cleanupError = $_
        }
        try {
            if (Test-Path -LiteralPath $passwordPath) {
                Remove-Item -LiteralPath $passwordPath -Force -ErrorAction Stop
            }
        } catch {
            if ($null -eq $cleanupError) { $cleanupError = $_ }
        }
        $initialAdmin = $null
        if ($null -ne $cleanupError) { throw $cleanupError }
    }
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

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments = @(), [string]$Label = $FilePath)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "$Label failed with exit code $LASTEXITCODE."
    }
}

function Get-PreferredNodePath {
    $portableNode = Join-Path $NodeHome "node.exe"
    if (Test-Path -LiteralPath $portableNode) { return $portableNode }
    return Get-CommandPath -Name "node"
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
    return Join-Path $PnpmHome "pnpm.cmd"
}

function Test-IsPnpmShim {
    param([string]$Runner)
    if (-not $Runner) { return $false }
    return ([IO.Path]::GetFullPath($Runner) -eq [IO.Path]::GetFullPath((Get-PnpmShimPath)))
}

function Get-PnpmVersion {
    param([string]$Runner)
    if (Test-IsPnpmShim -Runner $Runner) {
        return Get-ToolVersion -Path $Runner -Argument "--version"
    }
    return Get-ToolVersion -Path $Runner -Argument "pnpm" -ExtraArgument "--version"
}

function Ensure-FrontendToolchain {
    $node = Get-PreferredNodePath
    if (-not $node) { Stop-WithError "node is missing; run setup-windows.bat first." }
    $detectedNodeVersion = Get-ToolVersion -Path $node -Argument "--version"
    if ($detectedNodeVersion -ne "v$RequiredNodeVersion") {
        Stop-WithError "Node.js $RequiredNodeVersion is required; detected [$detectedNodeVersion]."
    }
    $nodeDirectory = Split-Path -Parent $node
    $env:Path = "$nodeDirectory;$env:Path"
    New-Item -ItemType Directory -Path $CorepackHome -Force | Out-Null
    New-Item -ItemType Directory -Path $NativeTempHome -Force | Out-Null
    $env:COREPACK_HOME = $CorepackHome
    $env:TEMP = $NativeTempHome
    $env:TMP = $NativeTempHome

    $runner = Get-PnpmShimPath
    if (-not (Test-Path -LiteralPath $runner)) {
        $runner = Get-CorepackPath -NodeDirectory $nodeDirectory
    }
    if (-not $runner) { Stop-WithError "pnpm runner is missing; rerun setup-windows.bat." }
    $detectedPnpmVersion = Get-PnpmVersion -Runner $runner
    if ($detectedPnpmVersion -ne $RequiredPnpmVersion) {
        Stop-WithError "pnpm $RequiredPnpmVersion is required; detected [$detectedPnpmVersion]."
    }
    return $runner
}

function Invoke-Pnpm {
    param([string]$Runner, [string[]]$Arguments, [string]$Label)
    if (Test-IsPnpmShim -Runner $Runner) {
        Invoke-Checked -FilePath $Runner -Arguments $Arguments -Label $Label
    } else {
        Invoke-Checked -FilePath $Runner -Arguments (@("pnpm") + $Arguments) -Label $Label
    }
}

function Test-TcpPort {
    param([int]$Port, [string]$HostName = "127.0.0.1")
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if ($task.Wait(3000) -and $client.Connected) { return $true }
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
    return $false
}

function Test-HttpEndpoint {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Wait-ForTcpPort {
    param([string]$Name, [int]$Port, [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort -Port $Port) {
            Write-Host "[OK] $Name is listening on 127.0.0.1:$Port" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }
    Stop-WithError "$Name did not open port $Port within $TimeoutSeconds seconds."
}

function Wait-ForHttpEndpoint {
    param([string]$Name, [string]$Url, [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpEndpoint -Url $Url) {
            Write-Host "[OK] $Name is ready: $Url" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }
    Stop-WithError "$Name did not become ready within $TimeoutSeconds seconds: $Url"
}

function Get-ServiceObject {
    param([pscustomobject]$Definition)
    $service = Get-Service -Name $Definition.ServiceName -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        Stop-WithError "$($Definition.Label) Windows service was not found: $($Definition.ServiceName)"
    }
    return $service
}

function Wait-ForServiceRunning {
    param([pscustomobject]$Definition, [int]$TimeoutSeconds = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $service = Get-ServiceObject -Definition $Definition
        if ($service.Status -eq "Running") { return }
        Start-Sleep -Seconds 1
    }
    Stop-WithError "$($Definition.Label) service did not become Running: $($Definition.ServiceName)"
}

function Write-ServiceOwnershipState {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    if ($script:ServiceOwnership.Count -eq 0) {
        if (Test-Path -LiteralPath $ServiceOwnershipPath) {
            Remove-Item -LiteralPath $ServiceOwnershipPath -Force
        }
        return
    }
    $script:ServiceOwnership | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ServiceOwnershipPath -Encoding UTF8
}

function Read-ServiceOwnershipState {
    if (-not (Test-Path -LiteralPath $ServiceOwnershipPath)) { return @() }
    try {
        $state = Get-Content -LiteralPath $ServiceOwnershipPath -Raw | ConvertFrom-Json
        if ($state -is [System.Array]) { return @($state) }
        return @($state)
    } catch {
        Stop-WithError "Cannot read service ownership state: $ServiceOwnershipPath"
    }
}

function Start-NativeServices {
    $previousOwnership = Read-ServiceOwnershipState
    $script:ServiceOwnership = @()
    foreach ($definition in $ServiceDefinitions) {
        $service = Get-ServiceObject -Definition $definition
        $startedByScript = $false
        if ($service.Status -ne "Running") {
            Write-Host "[run] Starting $($definition.Label) service $($definition.ServiceName)" -ForegroundColor Cyan
            Start-Service -Name $definition.ServiceName
            $startedByScript = $true
        } else {
            $previousEntry = @($previousOwnership | Where-Object { $_.ServiceName -eq $definition.ServiceName }) | Select-Object -First 1
            if ($previousEntry -and $previousEntry.StartedByScript) {
                $startedByScript = $true
            }
            Write-Host "[run] $($definition.Label) service already running: $($definition.ServiceName)" -ForegroundColor DarkGray
        }
        $script:ServiceOwnership += [pscustomobject]@{
            Key = $definition.Key
            Label = $definition.Label
            ServiceName = $definition.ServiceName
            StartedByScript = $startedByScript
        }
        Write-ServiceOwnershipState
    }
}

function Wait-ForNativeServices {
    foreach ($definition in $ServiceDefinitions) {
        Wait-ForServiceRunning -Definition $definition
        Wait-ForTcpPort -Name $definition.Label -Port $definition.Port
        if ($definition.HealthUrl) {
            Wait-ForHttpEndpoint -Name $definition.Label -Url $definition.HealthUrl
        }
    }
}

function Stop-OwnedServices {
    $state = Read-ServiceOwnershipState
    foreach ($entry in @($state | Sort-Object Key -Descending)) {
        if (-not $entry.StartedByScript) { continue }
        $service = Get-Service -Name $entry.ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $service) { continue }
        if ($service.Status -ne "Stopped") {
            Write-Host "[run] Stopping $($entry.Label) service $($entry.ServiceName)" -ForegroundColor Yellow
            Stop-Service -Name $entry.ServiceName -Force
        }
    }
    $script:ServiceOwnership = @()
    Write-ServiceOwnershipState
}

function Get-ProcessRecordPath {
    param([string]$Name)
    return Join-Path $RuntimeRoot "$Name.pid"
}

function Get-LogPath {
    param([string]$Name, [string]$Stream)
    return Join-Path $RuntimeRoot "$Name.$Stream.log"
}

function Get-ManagedProcess {
    param([string]$Name)
    $pidPath = Get-ProcessRecordPath -Name $Name
    if (-not (Test-Path -LiteralPath $pidPath)) { return $null }
    $record = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    $parts = $record -split "\|", 2
    if ($parts.Count -ne 2 -or $parts[0] -notmatch "^\d+$" -or $parts[1] -notmatch "^\d+$") {
        return $null
    }
    $process = Get-Process -Id ([int]$parts[0]) -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    try {
        if ($process.StartTime.ToUniversalTime().Ticks -ne [int64]$parts[1]) { return $null }
    } catch {
        return $null
    }
    return $process
}

function Remove-ProcessRecord {
    param([string]$Name)
    $pidPath = Get-ProcessRecordPath -Name $Name
    if (Test-Path -LiteralPath $pidPath) {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    }
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [int]$Port
    )
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    $existing = Get-ManagedProcess -Name $Name
    if ($existing) {
        Write-Host "[run] $Name already running, PID $($existing.Id)" -ForegroundColor DarkGray
        return
    }
    Remove-ProcessRecord -Name $Name
    if (Test-TcpPort -Port $Port) {
        Stop-WithError "Port $Port is already occupied by a process not owned by this runner."
    }
    if (-not (Test-Path -LiteralPath $FilePath)) {
        Stop-WithError "Executable is missing for $($Name): $FilePath"
    }
    $stdout = Get-LogPath -Name $Name -Stream "out"
    $stderr = Get-LogPath -Name $Name -Stream "err"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    $startTicks = $process.StartTime.ToUniversalTime().Ticks
    Set-Content -LiteralPath (Get-ProcessRecordPath -Name $Name) -Value "$($process.Id)|$startTicks" -Encoding ascii
    $script:StartedProcessNames += $Name
    Write-Host "[run] Started $Name, PID $($process.Id). Logs: $stdout / $stderr" -ForegroundColor Green
}

function Stop-ManagedProcess {
    param([string]$Name)
    $process = Get-ManagedProcess -Name $Name
    if ($process) {
        Write-Host "[run] Stopping $Name process tree, PID $($process.Id)" -ForegroundColor Yellow
        $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
        if (Test-Path -LiteralPath $taskkill) {
            & $taskkill /PID $process.Id /T /F *> $null
        } else {
            Stop-Process -Id $process.Id -Force
        }
    }
    Remove-ProcessRecord -Name $Name
}

function Test-ManagedProcessRunning {
    param([string]$Name)
    return ($null -ne (Get-ManagedProcess -Name $Name))
}

function Show-RecentLogs {
    foreach ($name in @("business-api", "web-console")) {
        foreach ($stream in @("out", "err")) {
            $path = Get-LogPath -Name $name -Stream $stream
            if (Test-Path -LiteralPath $path) {
                Write-Host "`n--- $path ---" -ForegroundColor DarkGray
                Get-Content -LiteralPath $path -Tail 80
            }
        }
    }
}

function Ensure-FrontendDependencies {
    param([string]$Runner)
    $vitePath = Join-Path $WebRoot "node_modules\.bin\vite.cmd"
    if (-not (Test-Path -LiteralPath $vitePath)) {
        Write-Host "[run] Installing frontend dependencies" -ForegroundColor Cyan
        Invoke-Pnpm -Runner $Runner -Arguments @("--dir", $WebRoot, "install", "--frozen-lockfile") -Label "frontend dependency installation"
    }
    if (-not (Test-Path -LiteralPath $vitePath)) {
        Stop-WithError "Frontend dependency installation completed without Vite: $vitePath"
    }
}

function Start-Backend {
    Start-ManagedProcess `
        -Name "business-api" `
        -FilePath $BackendWrapper `
        -Arguments @("spring-boot:run") `
        -WorkingDirectory $BackendRoot `
        -Port 8080
    Wait-ForHttpEndpoint -Name "business API health" -Url "http://127.0.0.1:$($env:TD_MANAGEMENT_PORT)/actuator/health" -TimeoutSeconds 180
}

function Start-Frontend {
    $runner = Ensure-FrontendToolchain
    Ensure-FrontendDependencies -Runner $runner
    $env:TOOL_DEFECT_DEV_API_TARGET = "http://127.0.0.1:8080"
    $arguments = @("dev")
    if (-not (Test-IsPnpmShim -Runner $runner)) {
        $arguments = @("pnpm", "dev")
    }
    Start-ManagedProcess `
        -Name "web-console" `
        -FilePath $runner `
        -Arguments $arguments `
        -WorkingDirectory $WebRoot `
        -Port 5173
    Wait-ForHttpEndpoint -Name "web development server" -Url "http://127.0.0.1:5173/" -TimeoutSeconds 60
}

function Stop-ManagedApplications {
    Stop-ManagedProcess -Name "web-console"
    Stop-ManagedProcess -Name "business-api"
}

function Rollback-Start {
    Write-Warning "Start failed; rolling back processes and Windows services started by this invocation."
    foreach ($name in @($script:StartedProcessNames | Select-Object -Unique)) {
        Stop-ManagedProcess -Name $name
    }
    Stop-OwnedServices
    $script:StartedProcessNames = @()
}

function Monitor-Stack {
    Write-Host "[run] Native development stack is running. Press Ctrl+C to stop owned services." -ForegroundColor Cyan
    while ($true) {
        if (Test-Path -LiteralPath $StopRequestPath) { return }
        if (-not (Test-ManagedProcessRunning -Name "business-api")) {
            Show-RecentLogs
            Stop-WithError "business API exited unexpectedly."
        }
        if (-not (Test-ManagedProcessRunning -Name "web-console")) {
            Show-RecentLogs
            Stop-WithError "web console exited unexpectedly."
        }
        foreach ($definition in $ServiceDefinitions) {
            $service = Get-ServiceObject -Definition $definition
            if ($service.Status -ne "Running") {
                Stop-WithError "$($definition.Label) service stopped unexpectedly: $($definition.ServiceName)"
            }
        }
        Start-Sleep -Seconds 2
    }
}

function Start-Stack {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    if (Test-Path -LiteralPath $StopRequestPath) {
        Remove-Item -LiteralPath $StopRequestPath -Force
    }
    $script:StartedProcessNames = @()
    Start-NativeServices
    Wait-ForNativeServices
    Start-Backend
    Initialize-LocalAdminIfRequired
    Start-Frontend

    Write-Host "`nNative development environment is ready:" -ForegroundColor Green
    Write-Host "  Web frontend       http://127.0.0.1:5173/"
    Write-Host "  Business API       http://127.0.0.1:8080/"
    Write-Host "  Health             http://127.0.0.1:$($env:TD_MANAGEMENT_PORT)/actuator/health"
    Write-Host "  RabbitMQ management http://127.0.0.1:15672/"
    Write-Host "  Object storage     http://127.0.0.1:9001/"
    Write-Host "  Prometheus         http://127.0.0.1:9090/"
    Write-Host "  Grafana            http://127.0.0.1:3000/"

    if ($Detach) {
        Write-Warning "Detached mode leaves owned processes and services running after this command exits."
        return
    }
    try {
        Monitor-Stack
    } finally {
        Stop-ManagedApplications
        Stop-OwnedServices
        if (Test-Path -LiteralPath $StopRequestPath) {
            Remove-Item -LiteralPath $StopRequestPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-Stack {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    Set-Content -LiteralPath $StopRequestPath -Value "stop requested" -Encoding ascii
    Stop-ManagedApplications
    Stop-OwnedServices
    if (Test-Path -LiteralPath $StopRequestPath) {
        Remove-Item -LiteralPath $StopRequestPath -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[OK] Owned Windows processes and services stopped; data was retained." -ForegroundColor Green
}

function Get-StatusValue {
    param([string]$Name)
    if (Test-ManagedProcessRunning -Name $Name) { return "RUNNING" }
    return "STOPPED"
}

function Show-Status {
    $failed = $false
    Write-Host "Applications:"
    foreach ($name in @("business-api", "web-console")) {
        $state = Get-StatusValue -Name $name
        Write-Host ("  {0,-16} {1}" -f $name, $state)
        if ($state -ne "RUNNING") { $failed = $true }
    }

    Write-Host "`nWindows services:"
    foreach ($definition in $ServiceDefinitions) {
        $service = Get-ServiceObject -Definition $definition
        $state = $service.Status.ToString().ToUpperInvariant()
        $ready = ($state -eq "RUNNING" -and (Test-TcpPort -Port $definition.Port))
        if ($ready -and $definition.HealthUrl) {
            $ready = Test-HttpEndpoint -Url $definition.HealthUrl
        }
        $healthState = if ($ready) { "READY" } else { "NOT_READY" }
        Write-Host ("  {0,-24} {1,-10} {2}" -f $definition.Label, $state, $healthState)
        if (-not $ready) { $failed = $true }
    }

    Write-Host "`nApplication ports:"
    $apiPortReady = Test-TcpPort -Port 8080
    $webPortReady = Test-TcpPort -Port 5173
    Write-Host ("  {0,-24} {1}" -f "business-api:8080", $(if ($apiPortReady) { "LISTENING" } else { "CLOSED" }))
    Write-Host ("  {0,-24} {1}" -f "web-console:5173", $(if ($webPortReady) { "LISTENING" } else { "CLOSED" }))

    Write-Host "`nApplication endpoints:"
    $apiReady = $apiPortReady -and (Test-HttpEndpoint -Url "http://127.0.0.1:$($env:TD_MANAGEMENT_PORT)/actuator/health")
    $webReady = $webPortReady -and (Test-HttpEndpoint -Url "http://127.0.0.1:5173/")
    Write-Host ("  {0,-24} {1}" -f "business-api health", $(if ($apiReady) { "READY" } else { "NOT_READY" }))
    Write-Host ("  {0,-24} {1}" -f "web-console", $(if ($webReady) { "READY" } else { "NOT_READY" }))
    if (-not $apiReady -or -not $webReady) { $failed = $true }

    if ($failed) {
        Stop-WithError "One or more native stack components are not ready."
    }
}

function Show-Logs {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    $paths = @()
    foreach ($name in @("business-api", "web-console")) {
        foreach ($stream in @("out", "err")) {
            $path = Get-LogPath -Name $name -Stream $stream
            if (-not (Test-Path -LiteralPath $path)) {
                New-Item -ItemType File -Path $path -Force | Out-Null
            }
            $paths += $path
        }
    }
    Write-Host "Following application logs. Press Ctrl+C to exit."
    Get-Content -LiteralPath $paths -Tail 100 -Wait
}

function Show-Help {
    Write-Host "Native Windows development runner. Docker and WSL are not used."
    Write-Host ".\run-windows.bat start -EnvFile .windows.env.ps1"
    Write-Host ".\run-windows.bat start -EnvFile .windows.env.ps1 -Detach"
    Write-Host "The first start with no local account interactively creates an administrator."
    Write-Host ".\run-windows.bat stop -EnvFile .windows.env.ps1"
    Write-Host ".\run-windows.bat status -EnvFile .windows.env.ps1"
    Write-Host ".\run-windows.bat logs"
    Write-Host "External PostgreSQL, RabbitMQ, object storage, telemetry, Prometheus, Grafana, Loki, and Tempo services are required."
}

try {
    Set-Location $ProjectRoot
    if ($Help) { $Action = "help" }
    switch ($Action.ToLowerInvariant()) {
        "help" {
            Show-Help
        }
        "logs" {
            Show-Logs
        }
        "start" {
            Load-Environment
            Ensure-Configuration
            $script:StartInProgress = $true
            Start-Stack
            $script:StartInProgress = $false
        }
        "stop" {
            Load-Environment
            Ensure-Configuration
            Stop-Stack
        }
        "status" {
            Load-Environment
            Ensure-Configuration
            Show-Status
        }
    }
} catch {
    if ($script:StartInProgress) {
        Rollback-Start
    }
    Write-Error $_.Exception.Message
    exit 1
}
