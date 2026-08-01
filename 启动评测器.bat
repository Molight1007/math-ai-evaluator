@echo off
chcp 936 >nul 2>&1
cd /d "%~dp0"
python "%~dp0≤‚ ‘π§æﬂ\launcher.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Program crashed. Press any key to exit.
    pause
)
