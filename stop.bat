@echo off
title Stopping Beltway Pirate
echo Stopping Beltway Pirate servers...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM node.exe 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /F /PID %%a 2>nul
echo Done.
timeout /t 2 /nobreak > nul
