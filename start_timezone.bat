@echo off
REM ============================================================
REM  TimeZone — Timesheet & Invoicing App launcher (Windows)
REM  Installs dependencies on first run, then starts the server.
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

REM Install dependencies if Flask is missing
python -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies ^(flask, waitress, hupper, openpyxl, reportlab^)...
  python -m pip install --upgrade pip
  python -m pip install flask waitress hupper openpyxl reportlab
)

echo.
echo Starting TimeZone...
echo Open http://127.0.0.1:5000 in your browser.
echo Press Ctrl+C to stop.
echo.
python app.py

pause
