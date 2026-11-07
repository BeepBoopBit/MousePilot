$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'test-target.ps1'
$action = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName MousePilotTestTarget -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask MousePilotTestTarget
