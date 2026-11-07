$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    uv run --extra build python -m PyInstaller --clean --noconfirm --onefile --name mousepilot-server --hidden-import pystray._win32 --add-data "src/mousepilot/uia.ps1;mousepilot" scripts/server-entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
    & "$root\dist\mousepilot-server.exe" --help
    if ($LASTEXITCODE -ne 0) { throw 'Executable smoke test failed' }
    uv run --extra build python scripts/collect-licenses.py
    if ($LASTEXITCODE -ne 0) { throw 'Dependency notice collection failed' }
    Copy-Item LICENSE,THIRD_PARTY_NOTICES.md -Destination dist -Force
    uv run --extra build python scripts/package-info.py --output dist/package-info.json
    if ($LASTEXITCODE -ne 0) { throw 'Package metadata failed' }
    $archive = Join-Path $root 'dist/mousepilot-windows-x64.zip'
    Compress-Archive -Path dist/mousepilot-server.exe,dist/third-party,dist/LICENSE,dist/THIRD_PARTY_NOTICES.md,dist/package-info.json -DestinationPath $archive -Force
    $stream = [System.IO.File]::OpenRead($archive)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $checksum = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
    [System.IO.File]::WriteAllText((Join-Path $root 'dist/SHA256SUMS'), "$checksum  mousepilot-windows-x64.zip`n", [System.Text.Encoding]::ASCII)
} finally { Pop-Location }
