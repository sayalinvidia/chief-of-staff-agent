@echo off
rem Run this BETWEEN test runs in Hermes Desktop.
rem 1. Saves what the last run did to the trackers (so it can be scored later).
rem 2. Resets the demo data, keeping the seeded emails (about 25 seconds).
rem Then start a NEW chat in Hermes Desktop for the next run.
setlocal
set "HERMES_HOME=%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff"
set "PYTHONUTF8=1"
cd /d "C:\Users\NVIDIA\chief-of-staff-agent"
echo Saving the tracker state from the last run...
"C:\Users\NVIDIA\chief-of-staff-runtime\python\python.exe" "C:\Users\NVIDIA\chief-of-staff-runtime\snapshot_tracker.py"
if errorlevel 1 (
  echo.
  echo COULD NOT SAVE THE TRACKER STATE - not resetting. See the message above.
  pause
  exit /b 1
)
echo.
echo Resetting the demo data...
"C:\Users\NVIDIA\chief-of-staff-runtime\python\python.exe" "C:\Users\NVIDIA\chief-of-staff-runtime\reset_keep_emails.py" > "%TEMP%\cos-reset.log" 2>&1
if errorlevel 1 (
  echo Quick reset refused, running the full reset instead...
  "C:\Users\NVIDIA\chief-of-staff-runtime\python\python.exe" demo\reset_workspace.py > "%TEMP%\cos-reset.log" 2>&1
  if errorlevel 1 (
    echo.
    echo RESET FAILED - see %TEMP%\cos-reset.log
    pause
    exit /b 1
  )
)
echo.
echo Ready. Start a NEW chat in Hermes Desktop for the next run.
pause
