@echo off
REM ============================================================
REM  TimeZone - Timesheet & Invoicing App
REM  Double-click this file to start the app. On the first run it
REM  installs what it needs, then starts the server. Keep the
REM  window open while you use TimeZone; close it (or press Ctrl+C)
REM  to stop.
REM ============================================================
setlocal
cd /d "%~dp0"

echo Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python was not found.
  echo.
  echo  1^) Install Python 3 from:  https://www.python.org/downloads/
  echo  2^) IMPORTANT: on the FIRST install screen, tick the box
  echo     "Add Python to PATH" at the bottom, THEN click Install.
  echo  3^) When it finishes, double-click this file again.
  echo.
  pause
  exit /b 1
)

REM Install dependencies on first run (when Flask isn't present yet)
python -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo Installing the app's components ^(one-time, may take a minute^)...
  python -m pip install --upgrade pip
  if exist requirements.txt (
    python -m pip install -r requirements.txt
  ) else (
    python -m pip install flask waitress hupper openpyxl reportlab
  )
)

echo.
echo  TimeZone is starting...
echo  Open this address in your web browser:   http://127.0.0.1:5000
echo  Keep this window open while you use the app. Close it to stop.
echo.
python app.py

pause
