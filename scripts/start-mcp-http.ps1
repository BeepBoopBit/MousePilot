param(
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$Device = 'windows',
    [int]$Port = 8766
)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Invalid port' }
if ($Device -notmatch '^[A-Za-z0-9_-]+$') { throw 'Device name must contain letters, digits, underscores, or hyphens' }
$root = Split-Path $PSScriptRoot -Parent
$profile = (Resolve-Path $Config).Path
$tokenFile = Join-Path $root 'mousepilot-mcp-token.txt'
$logFile = Join-Path $root 'mousepilot-mcp-http.log'
$arguments = "`"$root\scripts\http-mcp-entry.py`" --log-file `"$logFile`" --config `"$profile`" --device $Device mcp --transport streamable-http --http-port $Port --http-token-file `"$tokenFile`""
$action = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\pythonw.exe" -Argument $arguments -WorkingDirectory $root
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-ScheduledTaskPrincipal -UserId $identity.User.Value -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$trigger.Delay = 'PT10S'
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Stop-ScheduledTask MousePilotMCP -ErrorAction SilentlyContinue
# The venv launcher can leave a child interpreter alive briefly. Stop only this
# project's adapter, then wait for its listener to close before replacing it.
$entryPath = Join-Path $root 'scripts\http-mcp-entry.py'
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like 'python*' -and $_.CommandLine -and
    $_.CommandLine.IndexOf($entryPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
$portFree = $false
for ($attempt=0; $attempt -lt 50; $attempt++) {
    if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        $portFree = $true
        break
    }
    Start-Sleep -Milliseconds 100
}
if (-not $portFree) { throw "Port $Port is still occupied; no unrelated process was stopped" }
Register-ScheduledTask -TaskName MousePilotMCP -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask MousePilotMCP
$ready = $false
for ($attempt=0; $attempt -lt 50; $attempt++) {
    if (Test-Path $tokenFile) {
        try {
            $token = (Get-Content $tokenFile -Raw).Trim()
            $headers = @{Authorization="Bearer $token"; Accept='application/json, text/event-stream'}
            $body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"mousepilot-readiness","version":"1"}}}'
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/mcp" -Method Post -ContentType 'application/json' -Headers $headers -Body $body -TimeoutSec 1
            $info = $response.Content | ConvertFrom-Json
            if ($info.result.serverInfo.name -eq "mousepilot-$Device") {
                $sessionId = $response.Headers['Mcp-Session-Id']
                if ($sessionId) {
                    $headers['Mcp-Session-Id'] = $sessionId
                    $headers['Mcp-Protocol-Version'] = '2025-03-26'
                    try { Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/mcp" -Method Delete -Headers $headers -TimeoutSec 1 | Out-Null } catch { }
                }
                $ready = $true
                break
            }
        } catch { }
    }
    Start-Sleep -Milliseconds 200
}
if (-not $ready) { throw "HTTP MCP adapter did not become ready; inspect $logFile" }
Write-Output "MCP URL: http://127.0.0.1:$Port/mcp"
Write-Output "Bearer token file: $tokenFile"
