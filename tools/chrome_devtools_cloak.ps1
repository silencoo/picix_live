$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Uv = (Get-Command uv.exe -ErrorAction Stop).Source
$BrowserEnvironment = Join-Path $ProjectRoot ".venv-cloak"
$BrowserProject = Join-Path $PSScriptRoot "cloak_runtime"
$Launcher = Join-Path $PSScriptRoot "cloakbrowser_cdp.py"
$CacheDir = Join-Path $ProjectRoot ".cloakbrowser-cache"
$DataDir = Join-Path $ProjectRoot "unlock_data"
$ReadyFile = Join-Path $DataDir "cloakbrowser_cdp_ready.json"
$CdpPort = 9242
$CdpBaseUrl = "http://127.0.0.1:$CdpPort"
$CdpVersionUrl = "$CdpBaseUrl/json/version"
$browserProcess = $null
$stdoutLog = Join-Path $DataDir "cloakbrowser_stdout.log"
$stderrLog = Join-Path $DataDir "cloakbrowser_stderr.log"

function Test-CloakBrowserCdp {
    try {
        $response = Invoke-RestMethod -Uri $CdpVersionUrl -TimeoutSec 2
        return [bool]$response.webSocketDebuggerUrl
    }
    catch {
        return $false
    }
}

function Get-CloakBrowserReadyState {
    if (-not (Test-Path -LiteralPath $ReadyFile)) {
        return $null
    }
    try {
        $state = Get-Content -LiteralPath $ReadyFile -Raw | ConvertFrom-Json
        if ($state.ready -and $state.profile_version -eq 2) {
            return $state
        }
    }
    catch {
        return $null
    }
    return $null
}

if (-not (Test-CloakBrowserCdp)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    Remove-Item -LiteralPath $ReadyFile -Force -ErrorAction SilentlyContinue
    $env:CLOAKBROWSER_CACHE_DIR = $CacheDir
    $env:UV_PROJECT_ENVIRONMENT = $BrowserEnvironment

    $browserProcess = Start-Process `
        -FilePath $Uv `
        -ArgumentList @(
            "run",
            "--locked",
            "--project",
            $BrowserProject,
            "python",
            $Launcher,
            "--port",
            "$CdpPort"
        ) `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

}

$deadline = (Get-Date).AddSeconds(120)
$readyState = Get-CloakBrowserReadyState
while ((Get-Date) -lt $deadline -and (-not (Test-CloakBrowserCdp) -or $null -eq $readyState)) {
    if ($null -ne $browserProcess -and $browserProcess.HasExited) {
        throw "CloakBrowser uv process exited during startup. See $stderrLog"
    }
    Start-Sleep -Milliseconds 500
    $readyState = Get-CloakBrowserReadyState
}

if (-not (Test-CloakBrowserCdp)) {
    throw "CloakBrowser CDP endpoint did not become ready: $CdpBaseUrl"
}
if ($null -eq $readyState) {
    throw "CloakBrowser warm-up did not finish. See $stderrLog"
}
if (-not $readyState.cloudflare_passed) {
    [Console]::Error.WriteLine(
        "CloakBrowser started, but Picix Cloudflare warm-up did not pass: " +
        $readyState.error
    )
}

$Npx = (Get-Command npx.cmd -ErrorAction Stop).Source
& $Npx -y chrome-devtools-mcp@latest "--browser-url=$CdpBaseUrl"
exit $LASTEXITCODE
