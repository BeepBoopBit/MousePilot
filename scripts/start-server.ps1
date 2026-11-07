param([string]$Python = '', [string]$Executable = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if ($Executable) {
        $program = (Resolve-Path $Executable).Path
        $arguments = '--tray'
    } else {
        if ($Python) { uv sync --no-dev --python $Python } else { uv sync --no-dev }
        if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
        $program = "$root\.venv\Scripts\pythonw.exe"
        $arguments = '-m mousepilot.server --tray'
    }
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $action = New-ScheduledTaskAction -Execute $program -Argument $arguments -WorkingDirectory $root
    $principal = New-ScheduledTaskPrincipal -UserId $identity.User.Value -LogonType Interactive -RunLevel Limited
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $previousTask = Get-ScheduledTask -TaskName MousePilot -ErrorAction SilentlyContinue
    if ($previousTask) {
        try {
            $previousToken = (Get-Content mousepilot-token.txt -Raw -ErrorAction Stop).Trim()
            Invoke-RestMethod -Uri http://127.0.0.1:8765/ -Method Post -ContentType application/json -Headers @{Authorization="Bearer $previousToken"} -Body '{"command":"stop"}' -TimeoutSec 2 | Out-Null
        } catch { }
    }
    Stop-ScheduledTask -TaskName MousePilot -ErrorAction SilentlyContinue
    # A PyInstaller one-file child can outlive its scheduled-task launcher.
    if ($previousTask -and (Split-Path $previousTask.Actions[0].Execute -Leaf) -like 'mousepilot-server*.exe') {
        $previousProgram = $previousTask.Actions[0].Execute
        Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $previousProgram } | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        $existing = Get-ScheduledTask -TaskName MousePilot -ErrorAction SilentlyContinue
        if (-not $existing -or $existing.State -ne 'Running') { break }
        Start-Sleep -Milliseconds 100
    }
    # Allow the previous process to release its global hotkey before starting a replacement.
    Start-Sleep -Milliseconds 500
    Register-ScheduledTask -TaskName MousePilot -Action $action -Principal $principal -Trigger $trigger -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName MousePilot
    $ready = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        try {
            $token = (Get-Content mousepilot-token.txt -Raw -ErrorAction Stop).Trim()
            $info = Invoke-RestMethod -Uri http://127.0.0.1:8765/ -Method Post -ContentType application/json -Headers @{Authorization="Bearer $token"} -Body '{"command":"info"}' -TimeoutSec 1
            if ($info.device_id -eq (Get-Content mousepilot-device-id.txt -Raw).Trim()) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $ready) { throw 'Server did not become ready. Inspect mousepilot-server.log and the scheduled task result.' }
    Write-Output "MousePilot server ready: $($info.device_id)"
} finally { Pop-Location }
