@echo off
setlocal
cd /d "%~dp0..\frontend"
where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo Node.js/npm is required to run the Vite dashboard.
  echo Install Node.js LTS, then run this script again.
  exit /b 1
)
echo Installing frontend dependencies...
call npm.cmd install
if errorlevel 1 exit /b %errorlevel%
echo Starting ArjioBot frontend on http://localhost:5173/
call npm.cmd run dev -- --host 0.0.0.0
