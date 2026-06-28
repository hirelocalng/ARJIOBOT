@echo off
setlocal
cd /d "%~dp0..\backend"
if exist "..\..\.venv\Scripts\python.exe" (
  set PYTHON=..\..\.venv\Scripts\python.exe
) else (
  set PYTHON=python
)
if not exist "..\.pytest-tmp" mkdir "..\.pytest-tmp"
set BASETEMP=..\.pytest-tmp\pytest-%RANDOM%
set ADAPTER_MODE=MOCK
set LIVE_TRADING_ENABLED=false
%PYTHON% -m pytest arjiobot -q -p no:cacheprovider --basetemp %BASETEMP%
