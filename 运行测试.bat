@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0"
setlocal
set "MODE=%~1"
if not defined MODE set "MODE=full"
if /i not "%MODE%"=="full" if /i not "%MODE%"=="core" (
    echo Usage: 运行测试.bat [full^|core] [--no-pause]
    exit /b 2
)
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto setup_failed
)
".venv\Scripts\python.exe" scripts\run_tests.py %MODE% --install
set "TEST_EXIT=%ERRORLEVEL%"
goto finished
:setup_failed
set "TEST_EXIT=%ERRORLEVEL%"
echo Could not create project .venv. Install Python 3.10+ with the Python launcher.
:finished
if /i not "%~2"=="--no-pause" pause
exit /b %TEST_EXIT%
