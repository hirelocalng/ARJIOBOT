@echo off
setlocal
cd /d "%~dp0..\backend"
if exist "..\..\.venv\Scripts\python.exe" (
  set PYTHON=..\..\.venv\Scripts\python.exe
) else (
  set PYTHON=python
)
%PYTHON% -m arjiobot.api.dev_server
