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
    src = top_dirs[0]

    new_version = release["version"].lstrip("v")
    launcher    = APP_DIR / "start_reminders.vbs"

    # Single-quoted PS strings handle spaces in paths without escaping.
    def q(p: Path) -> str:
        return f"'{p}'"

    ps_lines = [
        "Start-Sleep -Seconds 3",
        # Strip read-only/hidden attributes GitHub zips sometimes set
        f"Get-ChildItem -Path {q(src)} -Recurse | ForEach-Object {{ $_.Attributes = 'Normal' }}",
        f"Get-ChildItem -Path {q(src)} -Filter '*.py' | Copy-Item -Destination {q(APP_DIR)} -Force",
        f"if (Test-Path {q(src / 'templates')}) {{",
        f"    robocopy {q(src / 'templates')} {q(APP_DIR / 'templates')} /E /IS /IT /IM >$null",
        f"}}",
        f"if (Test-Path {q(src / 'requirements.txt')}) {{",
        f"    Copy-Item -Path {q(src / 'requirements.txt')} -Destination {q(APP_DIR / 'requirements.txt')} -Force",
        f"    & pip install -r {q(APP_DIR / 'requirements.txt')} --quiet",
        f"}}",
        f"Set-Content -Path {q(VERSION_FILE)} -Value '{new_version}'",
        f"Remove-Item -Path {q(_STAGING_DIR)} -Recurse -Force -ErrorAction SilentlyContinue",
        f"& wscript {q(launcher)}",
    ]
    ps1 = _STAGING_DIR / "_apply_update.ps1"
    ps1.write_text("\n".join(ps_lines), encoding="utf-8")

    subprocess.Popen(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", str(ps1),
        ],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )


def remove_startup_shortcut() -> bool:
    """Delete the Windows Startup shortcut. Returns True if it existed."""
    startup   = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    shortcut  = startup / "JiraReminders.lnk"
    if shortcut.exists():
        shortcut.unlink()
        return True
    return False
