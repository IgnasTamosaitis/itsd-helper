import json
import shutil
from pathlib import Path
from datetime import datetime

DATA_DIR = Path.home() / ".jira-reminders"
TASKS_FILE = DATA_DIR / "tasks.json"
CONFIG_FILE = DATA_DIR / "config.json"
DEFAULT_TASK_COUNT = 5


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict | None:
    cfg = _load(CONFIG_FILE)
    return cfg if cfg else None


def save_config(cfg: dict) -> None:
    _save(CONFIG_FILE, cfg)


# ── Task completion + notes storage ──────────────────────────────────────────

class TaskStorage:
    def __init__(self):
        self._data: dict = _load(TASKS_FILE)

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def get(self, ticket_id: str, task_count: int = DEFAULT_TASK_COUNT) -> list[bool]:
        raw = self._data.get(ticket_id, [])
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
