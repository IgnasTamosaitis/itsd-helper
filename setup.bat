@echo off
setlocal

echo ============================================
echo  Jira New Joiner Reminders - Setup
echo ============================================
echo.

:: Check Python 3.11+ using either python.exe or the Windows launcher.
set "PYTHON_CMD="
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo ERROR: Python 3.11+ was not found.
    echo If you just installed Python, reopen this window and make sure
    echo the Python Launcher was installed.
    pause
    exit /b 1
)

echo Installing dependencies...
%PYTHON_CMD% -m pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo Creating startup shortcut in Start Menu...

set LAUNCHER=%~dp0start_reminders.vbs

:: Shortcut in Startup folder — write a PS1 then run it to avoid ^ escaping issues
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT=%STARTUP%\JiraReminders.lnk
set PS1=%TEMP%\make_shortcut.ps1

(
  echo $ws = New-Object -ComObject WScript.Shell
  echo $s  = $ws.CreateShortcut('%SHORTCUT%'^)
  echo $s.TargetPath      = 'wscript.exe'
  echo $s.Arguments       = '"%LAUNCHER%"'
  echo $s.WorkingDirectory = '%~dp0'
  echo $s.Description     = 'Jira New Joiner Reminders'
  echo $s.Save^(^)
) > "%PS1%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
del "%PS1%" 2>nul

echo.
echo ============================================
echo  Done!
echo  - App will start automatically on login.
echo  - To start now: double-click start_reminders.vbs
echo  - Look for the tray icon in the system tray.
echo  - Updates install automatically in the background.
echo  - To uninstall: right-click the tray icon, Uninstall.
echo ============================================
echo.
pause
