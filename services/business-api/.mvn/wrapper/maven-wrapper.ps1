$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceDirectory = Split-Path -Parent (Split-Path -Parent $scriptDirectory)
$propertiesPath = Join-Path $scriptDirectory "maven-wrapper.properties"
$properties = ConvertFrom-StringData (Get-Content -Raw $propertiesPath)

$distributionUrl = $properties.distributionUrl
$expectedSha256 = $properties.distributionSha256Sum.ToLowerInvariant()
if (-not $distributionUrl -or -not $expectedSha256) {
    throw "Maven Wrapper 配置缺少 distributionUrl 或 distributionSha256Sum"
}

$archiveName = [System.IO.Path]::GetFileName($distributionUrl)
$distributionName = $archiveName -replace "-bin\.zip$", ""
$mavenUserHome = if ($env:MAVEN_USER_HOME) {
    $env:MAVEN_USER_HOME
} else {
    Join-Path $HOME ".m2"
}
$installParent = Join-Path $mavenUserHome "wrapper/dists/$distributionName"
$installDirectory = Join-Path $installParent $expectedSha256
$mavenCommand = Join-Path $installDirectory "bin/mvn.cmd"

if (-not (Test-Path $mavenCommand -PathType Leaf)) {
    $temporaryDirectory = Join-Path (
        [System.IO.Path]::GetTempPath()
    ) ("td-maven-wrapper-" + [Guid]::NewGuid())
    New-Item $temporaryDirectory -ItemType Directory | Out-Null
    try {
        $archivePath = Join-Path $temporaryDirectory $archiveName
        Invoke-WebRequest -UseBasicParsing -Uri $distributionUrl -OutFile $archivePath
        $actualSha256 = (
            Get-FileHash $archivePath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if ($actualSha256 -ne $expectedSha256) {
            throw "Maven 发行包 SHA-256 校验失败"
        }
        Expand-Archive $archivePath -DestinationPath $temporaryDirectory
        $extractedDirectory = Join-Path $temporaryDirectory $distributionName
        if (-not (Test-Path (Join-Path $extractedDirectory "bin/mvn.cmd"))) {
            throw "Maven 发行包结构不合法"
        }
        New-Item $installParent -ItemType Directory -Force | Out-Null
        if (-not (Test-Path $installDirectory)) {
            Move-Item $extractedDirectory $installDirectory
        }
    } finally {
        if (Test-Path $temporaryDirectory) {
            Remove-Item $temporaryDirectory -Recurse -Force
        }
    }
}

& $mavenCommand @args
exit $LASTEXITCODE
