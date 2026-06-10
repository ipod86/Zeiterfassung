@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Erstelle virtuelle Umgebung...
  py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" run.py
pause
