@echo off
chcp 65001 > nul
REM ============================================================
REM  Lean 一键编译运行（类似 python xxx.py）
REM  用法: leanrun <文件.lean>
REM  例:   leanrun hello.lean
REM ============================================================
if "%~1"=="" (
    echo 用法: leanrun ^<文件.lean^>
    echo 例:   leanrun hello.lean
    pause
    exit /b 1
)
set "FILE=%~f1"
if not exist "%FILE%" (
    echo [错误] 找不到文件: %FILE%
    pause
    exit /b 1
)
echo [编译并运行] %FILE%
echo ------------------------------------------------------------
lean --run "%FILE%"
echo ------------------------------------------------------------
echo [退出码] %ERRORLEVEL%
if errorlevel 1 pause
