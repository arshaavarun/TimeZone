@echo off
REM ============================================================
REM  TimeZone — remove the logon auto-start task
REM ============================================================
setlocal
cd /d "%~dp0"
python install_autostart.py --remove
echo.
pause
