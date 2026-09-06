@echo off
setlocal
cd /d "%~dp0"
if exist "dist\MoyleSteg\MoyleSteg.exe" (
  start "" "dist\MoyleSteg\MoyleSteg.exe"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "main.py"
  exit /b 0
)
echo Please run Setup-Desktop.ps1 first, or use the portable EXE.
pause
