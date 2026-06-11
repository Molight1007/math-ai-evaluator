@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\"
set "ROOT=%ROOT:\????????\..\=\%"
cd /d "%ROOT%"

:: Auto-find Python path
set "PYTHON="
for /f "delims=" %%i in ('where.exe python 2^>nul') do (
    if not defined PYTHON set "PYTHON=%%i"
)

if not defined PYTHON (
    echo [ERROR] Python not found in PATH.
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Using Python: %PYTHON%
"%PYTHON%" "????\launcher.py"
pause
