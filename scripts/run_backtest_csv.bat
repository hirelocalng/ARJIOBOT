@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
  echo Usage: scripts\run_backtest_csv.bat data\BTCUSDT_1m.csv BTCUSDT PROFILE_F_VOLUME [DEFAULT_16_12_8]
  exit /b 1
)
if "%~2"=="" (
  echo Usage: scripts\run_backtest_csv.bat data\BTCUSDT_1m.csv BTCUSDT PROFILE_F_VOLUME [DEFAULT_16_12_8]
  exit /b 1
)
if "%~3"=="" (
  echo Usage: scripts\run_backtest_csv.bat data\BTCUSDT_1m.csv BTCUSDT PROFILE_F_VOLUME [DEFAULT_16_12_8]
  exit /b 1
)
if not exist "%~1" (
  echo CSV file not found: %~1
  exit /b 1
)
if exist "..\.venv\Scripts\python.exe" (
  set PYTHON=..\.venv\Scripts\python.exe
) else (
  set PYTHON=python
)
if "%~4"=="" (
  %PYTHON% scripts\backtest_csv.py "%~1" "%~2" "%~3" DEFAULT_16_12_8
) else (
  %PYTHON% scripts\backtest_csv.py "%~1" "%~2" "%~3" "%~4"
)
