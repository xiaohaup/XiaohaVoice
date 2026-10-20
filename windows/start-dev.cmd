@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
.venv\Scripts\python.exe -X utf8 prepare_components.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 vendor_opus.py devkit
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 main.py
exit /b %errorlevel%
