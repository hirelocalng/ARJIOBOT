@echo off
setlocal
cd /d "%~dp0..\backend"
if exist "..\..\.venv\Scripts\python.exe" (
  set PYTHON=..\..\.venv\Scripts\python.exe
) else (
  set PYTHON=python
)
if not exist "..\..\tmp" mkdir "..\..\tmp"
set BASETEMP=..\..\tmp\pytest-%RANDOM%
%PYTHON% -m pytest arjiobot -q -p no:cacheprovider --basetemp %BASETEMP%
