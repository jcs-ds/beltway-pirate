@echo off
title Beltway Pirate
echo ========================================
echo    Beltway Pirate
echo ========================================
echo.
echo Starting servers silently...
echo.

REM Run the hidden startup
cscript //nologo "%~dp0start-hidden.vbs"

echo Browser will open shortly.
echo.
echo To stop the servers, run stop.bat or close
echo any running python/node processes.
echo.
echo ========================================
echo (c) 2026 Beltway Pirate.
echo All rights reserved.
echo ========================================
echo.
timeout /t 5 /nobreak > nul
