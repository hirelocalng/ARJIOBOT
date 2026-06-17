@echo off
setlocal
cd /d "%~dp0.."
if exist "..\.venv\Scripts\python.exe" (
  set PYTHON=..\.venv\Scripts\python.exe
) else (
  set PYTHON=python
)
%PYTHON% scripts\validate_app.py
