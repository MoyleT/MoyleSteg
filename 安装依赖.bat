@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo py 命令执行失败，尝试 python 命令……
  python -m pip install -r requirements.txt
)
echo.
echo 依赖安装命令已结束。
pause
