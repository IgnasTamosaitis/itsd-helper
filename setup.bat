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
echo Storing shared Snipe-IT token in Windows Credential Manager...
python -c "import keyring; keyring.set_password('jira-reminders', 'snipeit-token', 'eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI1IiwianRpIjoiODk2MTZmODRiY2UwODM2ZGEwNzY2YWM3MGJhNThhY2JlMDFjYTdiYjAwODEzYWMxZjkxMGI2MmZiNWQ1OTAxNTNmZTY1NjNjNGM0OWUyZjMiLCJpYXQiOjE3NTkzOTA5NDYuMzkxMDE3LCJuYmYiOjE3NTkzOTA5NDYuMzkxMDE5LCJleHAiOjMwMjE2OTQ5NDYuMzc2NDg4LCJzdWIiOiIxODk2MiIsInNjb3BlcyI6W119.M2KctkkBSq5jFpg1St50ZumDKKbPvq5SXGOUSMsPkrgQDrgWhIC8hgw6yq9F-wJOCv07bx0MDUvhFmxkTdO-1ToWd6tyM0QjUclFTdpFiqCD71xPsTi4936DA1wM0BSHhiYig9Hr5XsHRFzhDDgVhO6q9dwUHguR7PBH9rv5Aj1eGPGtBTvjDvLB0ew4IEnubyf8QPvV_8I5i4G3luRHdsyRhAV1n_Ionljkc2zVv1Wh8AXQl3fjZUBuuMpOEGi2iTvTkg6jpy51HGPXa7T663UmZh3vaUWQD8VPmQEc-5P1jJgkTm1vgl2TI2wWvkPilv4O3XvUorTwq9yg8DTQsgsQ2re5MUDlR4ImlMH85GrrffrcqGVoQlKMl7yiVtwSE7J8EDuFjmuLyfSxQ4lv_oFNsGVMrtI4o3YjkR_XF_r9U2a3N9SMDzqJZvWiM1Ku80LKS8iFrDYyn0HlG7a9UlVQvLSeulblBcIxVNrF9-uK5fgYZfcAD8OIFWXknudqob0Mcf17nFeznai8joX_RRBM6t9Irhgs1KQEKZK0FhCUDmijZtpWBBv8xQT-B4jCXMuvNzNLA9Mtc68Eoj7cy_fcc4DYDYsmr8x41HHeqqnhVDA-V7HhrOU43llYJ_DqBxODvQECaqozdN5FCJfDzRCWKxvQHyzA8EZhI2QKyzo')"

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
echo  - Updates install automatically in the background.
echo  - To uninstall: right-click the tray icon, Uninstall.
echo ============================================
echo.
pause
