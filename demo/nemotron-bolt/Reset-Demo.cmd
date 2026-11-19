@echo off
rem Resets the Chief of Staff demo data in the connected Google account (the demo account)
rem to its starting state for today: seeded emails, drafts, calendar events, tasks,
rem the campaign tracker and reference tracker, the exec-review deck, the task
rem documents, and the local Second Brain notes. Takes about 40 seconds.
rem Run it before each demo run, then start a NEW chat in Hermes.
setlocal
set "HERMES_HOME=%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff"
set "PYTHONUTF8=1"
cd /d "C:\Users\NVIDIA\chief-of-staff-agent"
"C:\Users\NVIDIA\chief-of-staff-runtime\python\python.exe" demo\reset_workspace.py %*
if errorlevel 1 (
  echo.
  echo RESET FAILED - see the message above.
) else (
  echo.
  echo Reset complete. Start a new chat in Hermes before the next demo run.
)
pause
