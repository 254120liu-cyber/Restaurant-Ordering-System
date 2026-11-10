$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& '.venv/Scripts/python.exe' main.py demo
