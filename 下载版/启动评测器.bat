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
echo Starting Math Evaluator...
"%PYTHON%" "%ROOT%²âÊÔ¹¤¾ß\launcher.py" 2>"%TEMP%\math_eval_error.log"
if errorlevel 1 (
    echo.
    echo [ERROR] Program crashed. See log below:
    type "%TEMP%\math_eval_error.log"
    pause
)
