@echo off
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js 22.14 or later is required.
  pause
  exit /b 1
)
node scripts/platform.mjs start --background
if errorlevel 1 pause
