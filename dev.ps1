$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
Push-Location $root
try {
    & $python scripts/dev.py @args
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
