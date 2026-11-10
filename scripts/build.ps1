$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYINSTALLER_CONFIG_DIR=Join-Path (Get-Location) '.runtime/pyinstaller-cache'
& '.venv/Scripts/python.exe' -m PyInstaller --noconfirm --clean --windowed --name RestaurantOrdering --add-data 'sql;sql' main.py
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
Write-Host '运行程序位于 dist/RestaurantOrdering/RestaurantOrdering.exe。分发时保留整个文件夹。'
