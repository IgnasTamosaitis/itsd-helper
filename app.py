"""
Jira New Joiner Reminders
Runs in the system tray, polls Jira, and sends Windows notifications.
"""
import sys
import queue
import threading
import time
import tkinter as tk
from datetime import date, datetime, timedelta

import pystray
from PIL import Image, ImageDraw

from jira_client import JiraClient
from storage import TaskStorage, load_config, save_config
from ui import MainWindow, SetupDialog, TASKS

APP_NAME = "Jira Reminders"
MORNING_HOUR = 9   # send daily summary at 9:00 AM


# ── Tray icon ─────────────────────────────────────────────────────────────────

def _make_icon_image() -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill="#0052CC")
    d.text((20, 14), "JR", fill="white")
    return img


# ── Notifications ─────────────────────────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name=APP_NAME,
            timeout=12,
        )
    except Exception as e:
        print(f"[notify] {e}")


# ── Application ───────────────────────────────────────────────────────────────

class App:
    def __init__(self):
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title(APP_NAME)

        self._ui_queue: queue.Queue = queue.Queue()
        self._tickets: list[dict] = []
        self._window: MainWindow | None = None
        self._jira: JiraClient | None = None
        self._storage = TaskStorage()
        self._config: dict = {}
        self._tray: pystray.Icon | None = None

    # ── Startup ───────────────────────────────────────────────────────────────

    def run(self) -> None:
        cfg = load_config()
        if not cfg:
            cfg = self._run_setup(None)
            if cfg is None:
                sys.exit(0)
            save_config(cfg)

        self._apply_config(cfg)

        self._tray = pystray.Icon(
            "jira-reminders",
            _make_icon_image(),
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("Show tickets",  self._tray_show),
                pystray.MenuItem("Check now",     self._tray_check_now),
                pystray.MenuItem("Settings",      self._tray_settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit",          self._tray_quit),
            ),
        )
        self._tray.run_detached()

        threading.Thread(target=self._poll_loop,             daemon=True).start()
        threading.Thread(target=self._morning_summary_loop, daemon=True).start()

        self._root.after(100, self._drain_ui_queue)
        self._root.mainloop()

    def _apply_config(self, cfg: dict) -> None:
        self._config = cfg
        self._jira = JiraClient(cfg["jira_url"], cfg["email"], cfg["api_token"])

    # ── Background polling ────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        self._fetch_and_notify()
        interval = int(self._config.get("check_interval_minutes", 30)) * 60
        while True:
            time.sleep(interval)
            self._fetch_and_notify()

    def _fetch_and_notify(self) -> None:
        if not self._jira:
            return
        try:
            tickets = self._jira.get_new_joiner_tickets(
                self._config.get("jql", ""),
                self._config.get("date_field", "customfield_10980"),
            )
            self._tickets = tickets
            self._ui_queue.put(("update_tickets", tickets))
            self._send_per_ticket_notifications(tickets)
        except Exception as e:
            print(f"[poll] {e}")

    def _send_per_ticket_notifications(self, tickets: list[dict]) -> None:
        today  = date.today()
        remind = int(self._config.get("remind_days_before", 3))

        for t in tickets:
            sd = t.get("start_date")
            if sd is None:
                continue
            delta = (sd - today).days
            if delta < 0 or delta > remind:
                continue
            if self._storage.notified_today(t["id"]):
                continue

            done      = self._storage.completed_count(t["id"], len(TASKS))
            remaining = len(TASKS) - done
            day_msg   = "starts TODAY" if delta == 0 else (
                        "starts TOMORROW" if delta == 1 else
                        f"starts in {delta} day(s)")
            task_msg  = f"{remaining} task(s) still pending." if remaining else "All tasks done!"
            _notify(
                f"New Joiner: {t['name']}",
                f"{day_msg.capitalize()}  -  {task_msg}",
            )
            self._storage.mark_notified(t["id"])

    # ── Morning summary ───────────────────────────────────────────────────────

    def _morning_summary_loop(self) -> None:
        while True:
            now    = datetime.now()
            target = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            time.sleep((target - now).total_seconds())
            self._send_morning_summary()

    def _send_morning_summary(self) -> None:
        if self._storage.morning_summary_sent_today():
            return
        # Fetch fresh data at summary time
        if self._jira:
            try:
                self._tickets = self._jira.get_new_joiner_tickets(
                    self._config.get("jql", ""),
                    self._config.get("date_field", "customfield_10980"),
                )
                self._ui_queue.put(("update_tickets", self._tickets))
            except Exception:
                pass

        today        = date.today()
        week_tickets = [
            t for t in self._tickets
            if t.get("start_date") and 0 <= (t["start_date"] - today).days <= 7
        ]

        if not week_tickets:
            self._storage.mark_morning_summary_sent()
            return

        lines = []
        for t in week_tickets:
            delta = (t["start_date"] - today).days
            done  = self._storage.completed_count(t["id"], len(TASKS))
            when  = "TODAY" if delta == 0 else ("Tomorrow" if delta == 1
                    else t["start_date"].strftime("%b %d"))
            lines.append(f"{when}: {t['name']} [{done}/{len(TASKS)} tasks]")

        _notify(
            f"Good morning - {len(week_tickets)} joiner(s) this week",
            "\n".join(lines),
        )
        self._storage.mark_morning_summary_sent()

    # ── UI queue ──────────────────────────────────────────────────────────────

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                cmd, *args = self._ui_queue.get_nowait()
                if cmd == "show_window":
                    self._show_window()
                elif cmd == "update_tickets" and self._window:
                    self._window.update_tickets(args[0])
                elif cmd == "open_settings":
                    self._open_settings()
        except queue.Empty:
            pass
        self._root.after(100, self._drain_ui_queue)

    # ── Window management ─────────────────────────────────────────────────────

    def _show_window(self) -> None:
        if self._window and tk.Toplevel.winfo_exists(self._window):
            self._window.lift()
            self._window.deiconify()
            return
        self._window = MainWindow(
            self._root,
            self._tickets,
            self._storage,
            self._jira,
            on_refresh=self._manual_refresh,
        )

    def _manual_refresh(self) -> None:
        threading.Thread(target=self._fetch_and_notify, daemon=True).start()

    def _open_settings(self) -> None:
        dlg = SetupDialog(self._root, prefill=self._config)
        self._root.wait_window(dlg)
        if dlg.result:
            save_config(dlg.result)
            self._apply_config(dlg.result)
            threading.Thread(target=self._fetch_and_notify, daemon=True).start()

    def _run_setup(self, prefill) -> dict | None:
        dlg = SetupDialog(self._root, prefill=prefill)
        self._root.wait_window(dlg)
        return dlg.result

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _tray_show(self, icon=None, item=None):
        self._ui_queue.put(("show_window",))

    def _tray_check_now(self, icon=None, item=None):
        threading.Thread(target=self._fetch_and_notify, daemon=True).start()

    def _tray_settings(self, icon=None, item=None):
        self._ui_queue.put(("open_settings",))

    def _tray_quit(self, icon=None, item=None):
        if self._tray:
            self._tray.stop()
        self._root.quit()


if __name__ == "__main__":
    App().run()
