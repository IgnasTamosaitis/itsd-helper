import json
import os
import shutil
import stat
import subprocess
import threading
from pathlib import Path
from datetime import datetime

DATA_DIR = Path.home() / ".jira-reminders"
TASKS_FILE = DATA_DIR / "tasks.json"
CONFIG_FILE = DATA_DIR / "config.json"
DEFAULT_TASK_COUNT = 6

_KEYRING_SERVICE      = "jira-reminders"
_SNIPEIT_KEYRING_USER = "snipeit-token"

try:
    import keyring as _keyring
    _KEYRING_OK = True
except ImportError:
    _keyring = None
    _KEYRING_OK = False


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


_icacls_done: set[str] = set()  # paths that have already had ACLs hardened


def _set_owner_only(path: Path) -> None:
    """Restrict file access to the current user only.

    os.chmod is synchronous and fast.  The icacls call is slow on Windows
    (spawns a subprocess) so it runs once per path in a daemon thread — ACLs
    persist across writes, so there is no need to repeat it every save.
    """
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass

    path_str = str(path)
    if os.name == "nt" and path_str not in _icacls_done:
        _icacls_done.add(path_str)

        def _run_icacls():
            try:
                user = os.environ.get("USERNAME", "")
                if user:
                    subprocess.run(
                        ["icacls", path_str, "/inheritance:r",
                         "/grant:r", f"{user}:(R,W)"],
                        capture_output=True, check=False,
                    )
            except Exception:
                pass

        threading.Thread(target=_run_icacls, daemon=True).start()


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _set_owner_only(path)


# ── Credential helpers ────────────────────────────────────────────────────────

def save_token(email: str, token: str) -> None:
    """Save the API token in the OS credential store."""
    if _KEYRING_OK and email and token:
        _keyring.set_password(_KEYRING_SERVICE, email, token)


def load_token(email: str) -> str:
    """Load the API token from the OS credential store."""
    if _KEYRING_OK and email:
        return _keyring.get_password(_KEYRING_SERVICE, email) or ""
    return ""


def delete_token(email: str) -> None:
    if _KEYRING_OK and email:
        try:
            _keyring.delete_password(_KEYRING_SERVICE, email)
        except Exception:
            pass


def save_snipeit_token(token: str) -> None:
    if _KEYRING_OK and token:
        _keyring.set_password(_KEYRING_SERVICE, _SNIPEIT_KEYRING_USER, token)


def load_snipeit_token() -> str:
    if _KEYRING_OK:
        return _keyring.get_password(_KEYRING_SERVICE, _SNIPEIT_KEYRING_USER) or ""
    return ""


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict | None:
    cfg = _load(CONFIG_FILE)
    if not cfg:
        return None

    # One-time migration: move plaintext api_token out of the JSON file
    if "api_token" in cfg:
        token = cfg.pop("api_token", "")
        email = cfg.get("email", "")
        if token and email:
            save_token(email, token)
        _save(CONFIG_FILE, cfg)

    # Inject secrets from credential store
    email = cfg.get("email", "")
    cfg["api_token"]    = load_token(email)
    cfg["snipeit_token"] = load_snipeit_token()

    return cfg if cfg else None


def save_config(cfg: dict) -> None:
    email = cfg.get("email", "")
    token = cfg.get("api_token", "")
    if email and token:
        save_token(email, token)

    snipeit_token = cfg.get("snipeit_token", "")
    if snipeit_token:
        save_snipeit_token(snipeit_token)

    # Write everything except secrets to disk
    file_cfg = {k: v for k, v in cfg.items() if k not in ("api_token", "snipeit_token")}
    _save(CONFIG_FILE, file_cfg)


# ── Task completion + notes storage ──────────────────────────────────────────

class TaskStorage:
    def __init__(self):
        self._data: dict = _load(TASKS_FILE)

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def get(self, ticket_id: str, task_count: int = DEFAULT_TASK_COUNT) -> list[bool]:
        raw = self._data.get(ticket_id, [])
        if task_count == 6 and isinstance(raw, list) and len(raw) == 5:
            raw = [raw[0], raw[1], raw[2], raw[3], False, raw[4]]
            self._data[ticket_id] = raw
            _save(TASKS_FILE, self._data)
        result = list(raw) + [False] * task_count
        return result[:task_count]

    def set(self, ticket_id: str, task_index: int, done: bool, task_count: int = DEFAULT_TASK_COUNT) -> None:
        state = self.get(ticket_id, task_count)
        state[task_index] = done
        self._data[ticket_id] = state
        _save(TASKS_FILE, self._data)

    def completed_count(self, ticket_id: str, task_count: int = DEFAULT_TASK_COUNT) -> int:
        return sum(self.get(ticket_id, task_count))

    # ── Notes ─────────────────────────────────────────────────────────────────

    def get_notes(self, ticket_id: str) -> str:
        return self._data.get(f"__notes_{ticket_id}", "")

    def set_notes(self, ticket_id: str, text: str) -> None:
        self._data[f"__notes_{ticket_id}"] = text
        _save(TASKS_FILE, self._data)

    # Manual buddy override

    def get_manual_buddy(self, ticket_id: str) -> str:
        return self._data.get(f"__buddy_{ticket_id}", "")

    def set_manual_buddy(self, ticket_id: str, sam: str) -> None:
        self._data[f"__buddy_{ticket_id}"] = sam
        _save(TASKS_FILE, self._data)

    # Dismissed disabled buddy

    def get_dismissed_buddy(self, ticket_id: str) -> str:
        """Returns the display name of the dismissed disabled buddy, or ''."""
        return self._data.get(f"__dismissed_buddy_{ticket_id}", "")

    def set_dismissed_buddy(self, ticket_id: str, display_name: str) -> None:
        self._data[f"__dismissed_buddy_{ticket_id}"] = display_name
        _save(TASKS_FILE, self._data)

    # AD setup summary

    def get_ad_setup(self, ticket_id: str) -> dict:
        raw = self._data.get(f"__ad_setup_{ticket_id}", {})
        return raw if isinstance(raw, dict) else {}

    def mark_ad_setup(self, ticket_id: str, info: dict) -> None:
        self._data[f"__ad_setup_{ticket_id}"] = info
        _save(TASKS_FILE, self._data)

    def ad_setup_done(self, ticket_id: str) -> bool:
        return bool(self.get_ad_setup(ticket_id).get("completed_at"))

    # ── Per-ticket daily notification dedup ───────────────────────────────────

    def notified_today(self, ticket_id: str) -> bool:
        return self._data.get(f"__notified_{ticket_id}") == str(_today())

    def mark_notified(self, ticket_id: str) -> None:
        self._data[f"__notified_{ticket_id}"] = str(_today())
        _save(TASKS_FILE, self._data)

    # ── Morning summary dedup ─────────────────────────────────────────────────

    def morning_summary_sent_today(self) -> bool:
        return self._data.get("__morning_summary") == str(_today())

    def mark_morning_summary_sent(self) -> None:
        self._data["__morning_summary"] = str(_today())
        _save(TASKS_FILE, self._data)

    def backup_tasks(self) -> Path:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not TASKS_FILE.exists():
            _save(TASKS_FILE, self._data)
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"tasks_{stamp}.json"
        shutil.copy2(TASKS_FILE, backup_path)
        return backup_path


def _today():
    from datetime import date
    return date.today()
