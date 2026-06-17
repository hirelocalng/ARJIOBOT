@echo off
setlocal

if "%~1"=="" (
  echo Usage: scripts\run_profile_optimization.bat data\BTCUSDT-1m.csv BTCUSDT [DEFAULT_16_12_8]
  exit /b 1
)

if "%~2"=="" (
  echo Usage: scripts\run_profile_optimization.bat data\BTCUSDT-1m.csv BTCUSDT [DEFAULT_16_12_8]
  exit /b 1
)

set TIMEFRAME_PROFILE=%~3
if "%TIMEFRAME_PROFILE%"=="" set TIMEFRAME_PROFILE=DEFAULT_16_12_8

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\optimize_profiles.py "%~1" "%~2" "%TIMEFRAME_PROFILE%"
) else (
  python scripts\optimize_profiles.py "%~1" "%~2" "%TIMEFRAME_PROFILE%"
)

endlocal
