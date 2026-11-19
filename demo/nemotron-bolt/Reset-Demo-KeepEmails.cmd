@echo off
rem Resets the Chief of Staff demo WITHOUT touching the seeded emails (about 25 seconds).
rem Restores: both trackers, the exec-review deck, the task documents, calendar events,
rem tasks, Gmail drafts (all cleared) and the local Second Brain notes.
rem Keeps: the 82 seeded emails and their IDs, so the saved brief and links still work.
rem Email dates and read/unread state are not refreshed - run Reset-Demo.cmd once per demo day.
setlocal
set "HERMES_HOME=%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff"
set "PYTHONUTF8=1"
cd /d "C:\Users\NVIDIA\chief-of-staff-agent"
"C:\Users\NVIDIA\chief-of-staff-runtime\python\python.exe" "C:\Users\NVIDIA\chief-of-staff-runtime\reset_keep_emails.py"
if errorlevel 1 (
  echo.
  echo RESET FAILED - see the message above.
) else (
  echo.
  echo Reset complete, emails kept. Start a new chat in Hermes before the next demo run.
)
pause
