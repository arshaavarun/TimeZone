@echo off
REM ============================================================
REM  TimeZone — set up auto-start at Windows logon (one time)
REM  Double-click this once. No administrator rights needed.
REM ============================================================
setlocal
cd /d "%~dp0"

echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3 from python.org and retry.
  pause
  exit /b 1
)

REM Make sure the server dependencies (incl. waitress + hupper auto-reload) are present
python -c "import flask, waitress, hupper, openpyxl, reportlab" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies ^(flask, waitress, hupper, openpyxl, reportlab^)...
  python -m pip install flask waitress hupper openpyxl reportlab
)

echo.
python install_autostart.py
echo.
pause
