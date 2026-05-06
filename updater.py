"""Auto-update from GitHub Releases and uninstall helpers."""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import requests

GITHUB_REPO    = "IgnasTamosaitis/itsd-helper"
_RELEASES_API  = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

APP_DIR      = Path(__file__).resolve().parent
VERSION_FILE = APP_DIR / "version.txt"
_STAGING_DIR = APP_DIR / "_update_staging"


def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"


def _parse_ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def check_for_update() -> dict | None:
    """Return release info dict if a newer version exists on GitHub, else None."""
    try:
        r = requests.get(
            _RELEASES_API, timeout=10,
            headers={"Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        release = r.json()
        tag = release.get("tag_name", "")
        if _parse_ver(tag) > _parse_ver(current_version()):
            return {
                "version": tag,
                "zipball_url": release["zipball_url"],
                "notes": release.get("body", "").strip(),
            }
    except Exception as e:
        print(f"[updater] check failed: {e}")
    return None


def _force_remove(path: Path) -> None:
    """Remove a directory tree, resetting permissions first if needed."""
    if not path.exists():
        return
    for p in path.rglob("*"):
        try:
            p.chmod(0o777)
        except Exception:
            pass
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        # Last resort: let PowerShell do it
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Remove-Item -Path '{path}' -Recurse -Force -ErrorAction SilentlyContinue"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def _launch_ps1(src: Path, new_version: str) -> None:
    """Write and launch the PS1 that copies files and restarts the app."""
    launcher = APP_DIR / "start_reminders.vbs"
    log      = APP_DIR / "update.log"

    def q(p: Path) -> str:
        return f"'{p}'"

    def log_line(msg: str) -> str:
        return f"Add-Content -Path {q(log)} -Value \"$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') {msg}\""

    ps_lines = [
        "$ErrorActionPreference = 'Continue'",
        log_line(f"update started: {new_version}"),
        "Start-Sleep -Seconds 3",
        log_line("fixing attributes"),
        f"Get-ChildItem -Path {q(src)} -Recurse | ForEach-Object {{ try {{ $_.Attributes = 'Normal' }} catch {{}} }}",
        log_line("copying .py files"),
        f"Get-ChildItem -Path {q(src)} -Filter '*.py' | Copy-Item -Destination {q(APP_DIR)} -Force",
        log_line("stamping version"),
        f"Set-Content -Path {q(VERSION_FILE)} -Value '{new_version}'",
        log_line("copying templates"),
        f"if (Test-Path {q(src / 'templates')}) {{",
        f"    robocopy {q(src / 'templates')} {q(APP_DIR / 'templates')} /E /IS /IT /IM | Out-Null",
        f"}}",
        log_line("launching app"),
        f"& C:\\Windows\\System32\\wscript.exe {q(launcher)}",
        f"Start-Sleep -Seconds 2",
        log_line("running pip install"),
        f"if (Test-Path {q(src / 'requirements.txt')}) {{",
        f"    Copy-Item -Path {q(src / 'requirements.txt')} -Destination {q(APP_DIR / 'requirements.txt')} -Force",
        f"    & pip install -r {q(APP_DIR / 'requirements.txt')} --quiet",
        f"}}",
        log_line("cleaning up staging"),
        f"Remove-Item -Path {q(_STAGING_DIR)} -Recurse -Force -ErrorAction SilentlyContinue",
        log_line("done"),
    ]
    ps1 = _STAGING_DIR / "_apply_update.ps1"
    ps1.write_text("\n".join(ps_lines), encoding="utf-8")

    # VBS wrapper is required — subprocess.Popen with DETACHED_PROCESS fails
    # silently when launched from a consoleless pythonw process.
    ps1_escaped = str(ps1).replace('"', '""')
    vbs = _STAGING_DIR / "_run_update.vbs"
    vbs.write_text(
        'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run "powershell -NoProfile -ExecutionPolicy Bypass'
        f' -WindowStyle Hidden -File ""{ps1_escaped}""", 0, False\n',
        encoding="utf-8",
    )
    subprocess.Popen(
        ["wscript.exe", str(vbs)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )


def download_and_apply(release: dict, progress_cb=None) -> None:
    """Download the release zip and schedule file replacement after the app exits."""
    _force_remove(_STAGING_DIR)
    _STAGING_DIR.mkdir()

    zip_path = _STAGING_DIR / "update.zip"

    if progress_cb:
        progress_cb("Downloading…")
    r = requests.get(release["zipball_url"], stream=True, timeout=120)
    r.raise_for_status()
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=16384):
            f.write(chunk)

    if progress_cb:
        progress_cb("Extracting…")
    extract_dir = _STAGING_DIR / "extracted"
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    top_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
    if not top_dirs:
        raise RuntimeError("Unexpected zip layout — no top-level directory found.")

    _launch_ps1(src=top_dirs[0], new_version=release["version"].lstrip("v"))


def simulate_local_update(new_version: str = "test") -> None:
    """Stage from the current directory and run the update PS1 — for local testing only."""
    _force_remove(_STAGING_DIR)
    _STAGING_DIR.mkdir()
    src = _STAGING_DIR / "extracted" / "local-test"
    src.mkdir(parents=True)

    for f in APP_DIR.glob("*.py"):
        shutil.copy2(f, src / f.name)
    if (APP_DIR / "requirements.txt").exists():
        shutil.copy2(APP_DIR / "requirements.txt", src / "requirements.txt")
    templates_src = APP_DIR / "templates"
    if templates_src.exists():
        shutil.copytree(templates_src, src / "templates")

    _launch_ps1(src=src, new_version=new_version)


def _write_shortcut(shortcut: Path) -> None:
    launcher = APP_DIR / "start_reminders.vbs"
    ps = (
        f'$sh = New-Object -ComObject WScript.Shell; '
        f'$sc = $sh.CreateShortcut("{shortcut}"); '
        f'$sc.TargetPath = "C:\\\\WINDOWS\\\\system32\\\\wscript.exe"; '
        f'$sc.Arguments = \'"{launcher}"\'; '
        f'$sc.WorkingDirectory = "{APP_DIR}"; '
        f'$sc.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _ensure_shortcut(shortcut: Path) -> None:
    """Create or repair a shortcut so it points to the current install location."""
    launcher = APP_DIR / "start_reminders.vbs"
    expected_args = f'"{launcher}"'
    try:
        if shortcut.exists():
            ps_check = (
                f'$sh = New-Object -ComObject WScript.Shell; '
                f'$sc = $sh.CreateShortcut("{shortcut}"); '
                f'$sc.Arguments'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_check],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.stdout.strip() == expected_args:
                return  # already correct
        _write_shortcut(shortcut)
    except Exception as e:
        print(f"[updater] ensure_shortcut({shortcut.name}) failed: {e}")


def ensure_startup_shortcut() -> None:
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    _ensure_shortcut(startup / "JiraReminders.lnk")


def ensure_desktop_shortcut() -> None:
    import ctypes.wintypes
    buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(0, 0x0000, 0, 0, buf)  # CSIDL_DESKTOP
    desktop = Path(buf.value)
    _ensure_shortcut(desktop / "Jira Reminders.lnk")


def remove_startup_shortcut() -> bool:
    """Delete the Windows Startup shortcut. Returns True if it existed."""
    startup   = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    shortcut  = startup / "JiraReminders.lnk"
    if shortcut.exists():
        shortcut.unlink()
        return True
    return False
