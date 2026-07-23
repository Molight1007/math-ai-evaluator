@echo off
cd /d "d:\挑战杯\test_mathlib"

:: Clean up
if exist ".lake\packages" rmdir /s /q ".lake\packages"
if exist "lake-packages" rmdir /s /q "lake-packages"

:: Start lake update, log to file
echo === lake update started at %date% %time% === > lake_update.log
lake update >> lake_update.log 2>&1
echo === lake update finished at %date% %time%, exit code: %ERRORLEVEL% === >> lake_update.log

:: Write done marker
echo EXIT_CODE=%ERRORLEVEL% > lake_update_done.txt

echo Done! Press any key to close...
pause
