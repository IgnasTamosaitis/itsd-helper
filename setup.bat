@echo off
setlocal

echo ============================================
echo  Jira New Joiner Reminders - Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.11+ from python.org
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo ERROR: pip install failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo Creating startup shortcut in Start Menu...

:: Create a VBS launcher (no console window)
set LAUNCHER=%~dp0start_reminders.vbs
(
  echo Set WshShell = CreateObject^("WScript.Shell"^)
  echo WshShell.Run "pythonw ""%~dp0app.py""", 0, False
) > "%LAUNCHER%"

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
echo ============================================
echo.
pause
