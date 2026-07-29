param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$content = [System.IO.File]::ReadAllText($resolvedConfig)
$pattern = '(?ms)^\[mcp_servers\.chrome-devtools\]\r?\n.*?(?=^\[|\z)'
$matches = [regex]::Matches($content, $pattern)

if ($matches.Count -ne 1) {
    throw "Expected exactly one [mcp_servers.chrome-devtools] block; found $($matches.Count)."
}

$replacement = @'
[mcp_servers.chrome-devtools]
type = "stdio"
command = "powershell.exe"
args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "E:\\repo\\picix_live\\tools\\chrome_devtools_cloak.ps1"]
startup_timeout_ms = 120000

'@

$updated = [regex]::Replace($content, $pattern, $replacement, 1)
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "$resolvedConfig.cloakbrowser-$timestamp.bak"
$tempPath = "$resolvedConfig.cloakbrowser.tmp"

[System.IO.File]::WriteAllText(
    $tempPath,
    $updated,
    [System.Text.UTF8Encoding]::new($false)
)
Copy-Item -LiteralPath $resolvedConfig -Destination $backupPath -Force
Move-Item -LiteralPath $tempPath -Destination $resolvedConfig -Force

Write-Output "Updated: $resolvedConfig"
Write-Output "Backup:  $backupPath"
