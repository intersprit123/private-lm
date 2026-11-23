$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Building PrivateLM Windows Host..." -ForegroundColor Cyan
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { throw "Install Python 3.10+ from https://www.python.org/downloads/windows/ and enable Add Python to PATH." }
& $py.Source -m pip install --upgrade pip pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller." }
& $py.Source -m PyInstaller --noconfirm --clean --onefile --windowed --name PrivateLM-Windows-Host .\privatelm_windows_host.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
Write-Host "Build complete: $PSScriptRoot\dist\PrivateLM-Windows-Host.exe" -ForegroundColor Green
