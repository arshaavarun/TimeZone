@echo off
REM ============================================================
REM  TimeZone — stop the service and KEEP it stopped
REM  It will not auto-restart and will not come back at the next
REM  logon until you run service_start.bat.
REM ============================================================
setlocal
REM disable first so neither the logon trigger nor the crash-restart
REM rule can bring it back, then end the running instance
schtasks /Change /TN "TimeZone" /DISABLE >nul 2>&1
schtasks /End /TN "TimeZone" >nul 2>&1
echo.
echo TimeZone is stopped and disabled.
echo Run service_start.bat when you want it back.
pause
