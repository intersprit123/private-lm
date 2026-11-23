$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "Building PrivateLM Windows Host..." -ForegroundColor Cyan
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { throw "Install Python 3.10+ and enable Add Python to PATH." }
& $py.Source -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip." }
& $py.Source -m pip install -r .\requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Could not install build dependencies." }
& $py.Source -m py_compile .\privatelm_windows_host.py .\cluster_config.py .\cluster_protocol.py .\hardware.py
if ($LASTEXITCODE -ne 0) { throw "Python compile checks failed." }
& $py.Source -m PyInstaller --noconfirm --clean --onefile --windowed --paths $PSScriptRoot --hidden-import cluster_config --hidden-import cluster_protocol --hidden-import hardware --collect-all cryptography --collect-all qrcode --collect-all PIL --name PrivateLM-Windows-Host .\privatelm_windows_host.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
Write-Host "Build complete: $PSScriptRoot\dist\PrivateLM-Windows-Host.exe" -ForegroundColor Green
