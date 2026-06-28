@echo off
REM ============================================================
REM  TimeZone — start the service again after service_stop.bat
REM  Re-enables auto-start at logon and launches it now.
REM ============================================================
setlocal
schtasks /Change /TN "TimeZone" /ENABLE >nul 2>&1
schtasks /Run /TN "TimeZone"
echo.
echo TimeZone started (and will auto-start at logon again).
pause
