@echo off
REM ============================================================
REM  TimeZone — restart the background service
REM  Use this AFTER you change app code or templates, so the
REM  running server picks up the new logic.
REM ============================================================
setlocal
echo Stopping TimeZone...
schtasks /End /TN "TimeZone" >nul 2>&1
REM give Windows a moment to free port 5000 before starting again
timeout /t 2 /nobreak >nul
echo Starting TimeZone...
schtasks /Run /TN "TimeZone"
echo.
echo Done. Wait a second, then refresh your browser (Ctrl+F5).
pause
