@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Create a local venv first: py -3.13 -m venv .venv
  exit /b 1
)
.venv\Scripts\python.exe -X utf8 -m pip install -r requirements-windows.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 prepare_components.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 vendor_opus.py devkit
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 -m pytest -q tests
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 verify_shared.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -X utf8 build_windows.py --output "%~dp0dist\XiaohaVoice-%RANDOM%"
exit /b %errorlevel%
