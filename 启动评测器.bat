@echo off
chcp 936 > nul
set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PYTHON="
for /f "delims=" %%i in ('where.exe python') do if not defined PYTHON set "PYTHON=%%i"

if not defined PYTHON (
    echo [ERROR] Python not found in PATH.
    pause
    exit /b 1
)

echo Using Python: %PYTHON%
"%PYTHON%" "≤‚ ‘π§æﬂ\launcher.py"
pause
