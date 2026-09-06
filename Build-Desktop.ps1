$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Run Setup-Desktop.ps1 first.'
}
& '.\.venv\Scripts\python.exe' 'scripts\build_desktop.py'
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
