@echo off
chcp 936 >nul 2>&1
cd /d "%~dp0"

REM 清理旧编译缓存，确保加载最新源码（避免 .pyc 过期导致更新不生效）
for /d /r "%~dp0" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" >nul 2>&1

python "%~dp0测试工具\launcher.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Program crashed. Press any key to exit.
    pause
)
