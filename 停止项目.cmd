@echo off
cd /d "%~dp0"
node scripts/platform.mjs stop
if errorlevel 1 pause
