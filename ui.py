import threading
import tkinter as tk
from tkinter import messagebox
import webbrowser
from datetime import date
import unicodedata

from jira_client import extract_buddies_from_comments, is_sam_account

TASKS = [
    "Active Directory account setup",
    "Axapta account import/creation",
    "Hardware preparation (laptop, phone, SIM card activation, headphones)",
    "Assign hardware & licenses in Snipe-IT",
    "Physical access card creation",
]
AD_TASK_INDEX = 0

BG     = "#F7F8FA"
ACCENT = "#0C66E4"
WHITE  = "#FFFFFF"
GREEN  = "#1F845A"
GRAY   = "#5E6C84"
RED    = "#C9372C"
TEXT   = "#172B4D"
BORDER = "#DFE3EA"
SOFT_BLUE = "#E9F2FF"


class MainWindow(tk.Toplevel):
    def __init__(self, parent, tickets: list, storage, jira_client, on_refresh):
        super().__init__(parent)
        self.tickets   = tickets
        self.storage   = storage
        self.jira      = jira_client
        self.on_refresh = on_refresh
        self._sel: int | None = None
        self._task_vars: list[tk.BooleanVar] = []
        self._notes_box: tk.Text | None = None
        self._notes_ticket_id: str | None = None
        self._notes_save_job = None
        self._ad_btn: tk.Button | None = None
        self._ask_btn: tk.Button | None = None
        self._comments_cache: dict = {}
        self._buddy_hint: dict = {}    # ticket_id -> {name, author, date} | None
        self._buddy_fetched: set = set()
        self._buddy_box_frame: tk.Frame | None = None
        self._buddy_box_ticket: str | None = None
        self._manual_buddies: set = set()        # ticket_ids with a persisted manual buddy
        self._dismissed_buddy_names: dict = {}   # ticket_id -> display name of cleared buddy
        self._load_manual_buddies()
        self._load_dismissed_buddies()

        self.title("ITSD Jira Helper")
        self.geometry("980x620")
        self.resizable(True, True)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self._build()
        self._refresh_list()
        self._update_ad_button()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Top bar
        bar = tk.Frame(self, bg=ACCENT, height=44)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="  New Joiner Reminders", bg=ACCENT, fg=WHITE,
                 font=("Segoe UI", 13, "bold")).pack(side="left", pady=10)
        self._make_btn(bar, "Refresh", self._do_refresh, WHITE, ACCENT).pack(
            side="right", padx=10, pady=8)

        # Body: left (list) + right (detail)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # Left panel
        left = tk.Frame(body, bg=WHITE, width=420)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="Upcoming joiners", bg=WHITE, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(14, 6))

        self._listbox = tk.Listbox(
            left, selectmode="single", relief="flat", bd=0,
            bg=WHITE, fg=TEXT, font=("Segoe UI", 10),
            selectbackground=SOFT_BLUE, selectforeground=ACCENT,
            activestyle="none", highlightthickness=0,
        )
        self._listbox.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        # Right panel
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self._right = right

        self._hint = tk.Label(right, text="Select a joiner to view their checklist",
                              bg=BG, fg=GRAY, font=("Segoe UI", 11))
        self._hint.place(relx=0.5, rely=0.5, anchor="center")

        self._detail_sb = tk.Scrollbar(right, orient="vertical")
        self._detail_canvas = tk.Canvas(right, bg=BG, highlightthickness=0,
                                        yscrollcommand=self._detail_sb.set)
        self._detail_sb.configure(command=self._detail_canvas.yview)
        self._detail = tk.Frame(self._detail_canvas, bg=BG)
        self._detail_wid = self._detail_canvas.create_window(
            (0, 0), window=self._detail, anchor="nw")
        self._detail.bind("<Configure>", lambda e: self._detail_canvas.configure(
            scrollregion=self._detail_canvas.bbox("all")))
        self._detail_canvas.bind("<Configure>", lambda e: self._detail_canvas.itemconfig(
            self._detail_wid, width=e.width))

        # Bottom bar
        btm = tk.Frame(self, bg="#EEF2F7", height=46)
        btm.pack(fill="x", side="bottom")
        btm.pack_propagate(False)
        self._status = tk.StringVar(value="")
        tk.Label(btm, textvariable=self._status, bg="#EEF2F7", fg=GRAY,
                 font=("Segoe UI", 9)).pack(side="left", padx=12)
        self._make_btn(btm, "Open in Jira", self._open_jira, WHITE, ACCENT).pack(
            side="right", padx=10, pady=8)
        self._ad_btn = self._make_btn(btm, "AD Setup", self._open_ad_setup, WHITE, "#00875A")
        self._ad_btn.pack(side="right", padx=(0, 4), pady=8)
        self._make_btn(btm, "Back up data", self._backup_data, ACCENT, SOFT_BLUE).pack(
            side="right", padx=(0, 4), pady=8)
        self._ask_btn = self._make_btn(btm, "Ask reporter", self._open_ask_reporter,
                                       WHITE, "#6554C0")
        self._ask_btn.pack(side="right", padx=(0, 4), pady=8)

    # ── Ticket list ───────────────────────────────────────────────────────────

    def _refresh_list(self):
        self._listbox.delete(0, "end")
        today = date.today()
        for i, t in enumerate(self.tickets):
            done  = self.storage.completed_count(t["id"], len(TASKS))
            sd    = t["start_date"]
            color = TEXT  # default - more than 7 days away or no date

            if sd:
                delta = (sd - today).days
                if delta < 0:
                    date_tag = f"started {-delta}d ago"
                    color = GRAY
                elif delta == 0:
                    date_tag = "TODAY"
                    color = RED
                elif delta == 1:
                    date_tag = "TOMORROW"
                    color = RED
                elif delta <= 7:
                    date_tag = f"in {delta}d"
                    color = GREEN
                else:
                    date_tag = f"{sd.strftime('%b %d')} ({delta}d)"
            else:
                date_tag = "no date"

            ad_tag = "  AD done" if self.storage.ad_setup_done(t["id"]) else ""
            label = f"  {t['key']}  {t['name']}  [{done}/{len(TASKS)}]  {date_tag}{ad_tag}"
            self._listbox.insert("end", label)
            self._listbox.itemconfig(i, fg=color)

        if not self.tickets:
            self._listbox.insert("end", "  No tickets found")
            self._status.set("No new joiner tickets found.")

    def _on_select(self, _=None):
        sel = self._listbox.curselection()
        if not sel or sel[0] >= len(self.tickets):
            return
        self._save_current_notes()
        self._sel = sel[0]
        self._show_detail(self.tickets[self._sel])
        self._update_ad_button()

    # ── Detail / task panel ───────────────────────────────────────────────────

    def _show_detail(self, t: dict):
        self._save_current_notes()
        self._sync_ad_task(t["id"])
        self._hint.place_forget()
        for w in self._detail.winfo_children():
            w.destroy()
        self._task_vars = []
        self._notes_box = None
        self._notes_ticket_id = None
        self._detail_sb.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne", width=16)
        self._detail_canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0, width=-16)
        self._detail_canvas.yview_moveto(0.0)

        # Name heading + joiner type badge
        is_rejoiner = t.get("rejoiner", "").lower() == "yes"
        name_row = tk.Frame(self._detail, bg=BG)
        name_row.pack(anchor="w", padx=24, pady=(20, 2))
        tk.Label(name_row, text=t["name"], bg=BG, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        badge_text = "Rejoiner" if is_rejoiner else "New Joiner"
        badge_bg   = "#FF991F" if is_rejoiner else "#E3FCEF"
        badge_fg   = WHITE     if is_rejoiner else GREEN
        tk.Label(name_row, text=badge_text, bg=badge_bg, fg=badge_fg,
                 font=("Segoe UI", 9, "bold"), padx=8, pady=3,
                 relief="flat").pack(side="left", padx=(12, 0))

        # Meta row
        today = date.today()
        sd = t["start_date"]
        if sd:
            delta = (sd - today).days
            if delta < 0:
                date_text = f"{sd}  (started {-delta} day(s) ago)"
                date_color = GRAY
            elif delta == 0:
                date_text = f"{sd}  - STARTS TODAY"
                date_color = RED
            elif delta <= 3:
                date_text = f"{sd}  - in {delta} day(s)"
                date_color = "#FF991F"
            else:
                date_text = f"{sd}  - in {delta} day(s)"
                date_color = TEXT
        else:
            date_text  = "Start date: not set"
            date_color = GRAY

        tk.Label(self._detail, text=date_text, bg=BG, fg=date_color,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=24, pady=(0, 2))

        meta_parts = []
        if t.get("position"): meta_parts.append(t["position"])
        if t.get("office"):   meta_parts.append(t["office"])
        if t.get("manager"):  meta_parts.append(f"Mgr: {t['manager']}")
        if t.get("status"):   meta_parts.append(t["status"])
        if meta_parts:
            tk.Label(self._detail, text="  |  ".join(meta_parts), bg=BG, fg=GRAY,
                     font=("Segoe UI", 9), wraplength=500, justify="left").pack(
                     anchor="w", padx=24, pady=(0, 2))

        tk.Label(self._detail, text=t["key"], bg=BG, fg=GRAY,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=24, pady=(0, 10))

        self._show_ad_setup_summary(t)
        self._show_buddy_box(t)

        # Divider
        tk.Frame(self._detail, bg=BORDER, height=1).pack(fill="x", padx=24, pady=(0, 10))

        # Tasks
        tk.Label(self._detail, text="Onboarding checklist", bg=BG, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 6))

        state = self.storage.get(t["id"], len(TASKS))
        for i, task in enumerate(TASKS):
            var = tk.BooleanVar(value=state[i])
            self._task_vars.append(var)
            row = tk.Frame(self._detail, bg=BG)
            row.pack(fill="x", padx=20, pady=3)
            tk.Checkbutton(
                row, variable=var, bg=BG, activebackground=BG,
                command=lambda idx=i, v=var, tid=t["id"]: self._toggle(tid, idx, v),
            ).pack(side="left")
            fg = GRAY if var.get() else TEXT
            tk.Label(row, text=task, bg=BG, fg=fg,
                     font=("Segoe UI", 10), wraplength=500, justify="left",
                     anchor="w").pack(side="left")

        # Notes
        tk.Frame(self._detail, bg=BORDER, height=1).pack(fill="x", padx=24, pady=(14, 8))
        tk.Label(self._detail, text="Notes", bg=BG, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 4))

        notes_box = tk.Text(
            self._detail, height=4, relief="solid", bd=1,
            font=("Segoe UI", 10), bg=WHITE, fg=TEXT,
            wrap="word", padx=6, pady=4,
        )
        notes_box.insert("1.0", self.storage.get_notes(t["id"]))
        notes_box.pack(fill="x", padx=24, pady=(0, 8))
        self._notes_box = notes_box
        self._notes_ticket_id = t["id"]
        notes_box.bind("<KeyRelease>",
                       lambda e, tid=t["id"], nb=notes_box:
                       self._queue_notes_save(tid, nb))
        notes_box.bind("<FocusOut>",
                       lambda e, tid=t["id"], nb=notes_box:
                       self._save_notes(tid, nb))

        # Comments
        tk.Frame(self._detail, bg=BORDER, height=1).pack(fill="x", padx=24, pady=(14, 8))
        tk.Label(self._detail, text="Jira comments", bg=BG, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 4))

        comments_frame = tk.Frame(self._detail, bg=BG)
        comments_frame.pack(fill="x", padx=24, pady=(0, 16))
        comments_frame.columnconfigure(0, weight=1)

        comments_box = tk.Text(
            comments_frame, height=10, relief="solid", bd=1,
            font=("Segoe UI", 9), bg=WHITE, fg=TEXT,
            wrap="word", padx=6, pady=4, state="disabled",
        )
        comments_sb = tk.Scrollbar(comments_frame, orient="vertical",
                                   command=comments_box.yview)
        comments_box.configure(yscrollcommand=comments_sb.set)
        comments_box.grid(row=0, column=0, sticky="ew")
        comments_sb.grid(row=0, column=1, sticky="ns")

        if t["key"] in self._comments_cache:
            cached_comments = self._comments_cache[t["key"]]
            self._populate_comments(comments_box, cached_comments)
            if t["id"] not in self._buddy_fetched:
                buddy = self._resolve_buddy_from_comments(t["id"], cached_comments)
                self._buddy_hint[t["id"]] = buddy
                self._buddy_fetched.add(t["id"])
                self._refresh_buddy_box(t["id"], buddy)
        else:
            self._set_comments_text(comments_box, "Loading…")

        # Always refresh comments in the background so new Jira replies show up
        # even when the app has been running with a stale in-memory cache.
        threading.Thread(
            target=self._fetch_comments,
            args=(t["key"], t["id"], comments_box),
            daemon=True,
        ).start()

        self._bind_detail_scroll(self._detail)
        notes_box.bind("<MouseWheel>",
            lambda e: notes_box.yview_scroll(int(-1 * e.delta / 120), "units"))
        comments_box.bind("<MouseWheel>",
            lambda e: comments_box.yview_scroll(int(-1 * e.delta / 120), "units"))

        done = self.storage.completed_count(t["id"], len(TASKS))
        self._status.set(f"  {done}/{len(TASKS)} tasks completed")
        self._update_ad_button()
        self._update_ask_btn()

    def _bind_detail_scroll(self, widget):
        """Recursively bind mousewheel on all detail children to scroll the outer canvas."""
        widget.bind("<MouseWheel>",
            lambda e: self._detail_canvas.yview_scroll(int(-1 * e.delta / 120), "units"))
        for child in widget.winfo_children():
            self._bind_detail_scroll(child)

    def _toggle(self, ticket_id: str, idx: int, var: tk.BooleanVar):
        self.storage.set(ticket_id, idx, var.get(), len(TASKS))
        done = self.storage.completed_count(ticket_id, len(TASKS))
        self._status.set(f"  {done}/{len(TASKS)} tasks completed")
        self._refresh_list()
        if self._sel is not None:
            self._listbox.selection_set(self._sel)

    def _queue_notes_save(self, ticket_id: str, notes_box: tk.Text):
        self._cancel_notes_save()
        self._notes_save_job = self.after(
            400, lambda: self._save_notes(ticket_id, notes_box))

    def _save_notes(self, ticket_id: str, notes_box: tk.Text):
        self._cancel_notes_save()
        try:
            if notes_box.winfo_exists():
                self.storage.set_notes(ticket_id, notes_box.get("1.0", "end-1c"))
        except tk.TclError:
            pass

    def _save_current_notes(self):
        if self._notes_ticket_id and self._notes_box:
            self._save_notes(self._notes_ticket_id, self._notes_box)

    def _cancel_notes_save(self):
        if self._notes_save_job is not None:
            try:
                self.after_cancel(self._notes_save_job)
            except tk.TclError:
                pass
            self._notes_save_job = None

    # ── Buddy box ─────────────────────────────────────────────────────────────

    def _load_manual_buddies(self):
        for t in self.tickets:
            sam = self.storage.get_manual_buddy(t["id"])
            if sam:
                self._buddy_hint[t["id"]] = {"name": sam, "author": "manual", "date": ""}
                self._buddy_fetched.add(t["id"])
                self._manual_buddies.add(t["id"])

    def _load_dismissed_buddies(self):
        for t in self.tickets:
            tid = t["id"]
            if tid in self._manual_buddies:
                continue  # manual buddy was set after dismissal — it wins
            name = self.storage.get_dismissed_buddy(tid)
            if name:
                self._dismissed_buddy_names[tid] = unicodedata.normalize("NFC", name)

    def _show_buddy_box(self, t: dict):
        tid = t["id"]
        frame = tk.Frame(self._detail, bg=SOFT_BLUE,
                         highlightbackground=ACCENT, highlightthickness=1)
        frame.pack(fill="x", padx=24, pady=(2, 10))
        self._buddy_box_frame = frame
        self._buddy_box_ticket = tid

        if tid in self._buddy_fetched:
            buddy = self._buddy_hint.get(tid)
            if buddy:
                self._fill_buddy_box(frame, buddy, tid)
                if not buddy.get("multiple") and "disabled" not in buddy:
                    threading.Thread(
                        target=self._check_buddy_disabled,
                        args=(tid, buddy), daemon=True,
                    ).start()
            else:
                self._draw_buddy_no_result(frame, tid)
        else:
            tk.Label(frame, text="Scanning comments for buddy info…",
                     bg=SOFT_BLUE, fg=GRAY,
                     font=("Segoe UI", 9, "italic")).pack(anchor="w", padx=10, pady=6)

    def _fill_buddy_box(self, frame: tk.Frame, buddy: dict, ticket_id: str):
        for w in frame.winfo_children():
            w.destroy()

        if buddy.get("multiple"):
            self._fill_multiple_buddy_box(frame, buddy, ticket_id)
            return

        if buddy.get("disabled"):
            self._fill_disabled_buddy_box(frame, buddy, ticket_id)
            return

        frame.configure(bg=SOFT_BLUE, highlightbackground=ACCENT)
        tk.Label(frame, text="Suggested buddy", bg=SOFT_BLUE, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(frame, text=self._buddy_caption(buddy), bg=SOFT_BLUE, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(2, 0))
        source = "Set manually" if buddy.get("author") == "manual" else f"From comment by {buddy['author']}  •  {buddy['date']}"
        tk.Label(frame, text=source, bg=SOFT_BLUE, fg=GRAY,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(2, 8))

    @staticmethod
    def _buddy_caption(buddy: dict) -> str:
        display_name = buddy.get("display_name", "")
        sam = buddy.get("name", "")
        if display_name and display_name.lower() != sam.lower():
            return f"{display_name} ({sam})"
        return sam or display_name

    def _fill_multiple_buddy_box(self, frame: tk.Frame, buddy: dict, ticket_id: str):
        frame.configure(bg="#FFF4E5", highlightbackground="#FF991F", highlightthickness=1)

        tk.Label(frame, text="Multiple buddies found — choose one",
                 bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        source = f"From comment by {buddy['author']}  •  {buddy['date']}"
        tk.Label(frame, text=source, bg="#FFF4E5", fg=GRAY,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(2, 4))
        tk.Label(frame,
                 text="The comment mentioned more than one possible buddy. Choose the account to use as the template.",
                 bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9), wraplength=480, justify="left").pack(
                     anchor="w", padx=10, pady=(0, 8))

        active_candidates = 0
        for candidate in buddy.get("candidates", []):
            card_bg = "#FFFFFF" if not candidate.get("disabled") else "#FFEBE6"
            card = tk.Frame(frame, bg=card_bg, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", padx=10, pady=(0, 6))

            top = tk.Frame(card, bg=card_bg)
            top.pack(fill="x", padx=8, pady=(8, 2))
            tk.Label(top, text=self._buddy_caption(candidate), bg=card_bg, fg=TEXT,
                     font=("Segoe UI", 10, "bold")).pack(side="left")
            if candidate.get("disabled"):
                tk.Label(top, text="Disabled in AD", bg=card_bg, fg=RED,
                         font=("Segoe UI", 8, "bold")).pack(side="right")
            else:
                active_candidates += 1

            status = "This account cannot be used as a template." if candidate.get("disabled") else "Ready to use as the template account."
            tk.Label(card, text=status, bg=card_bg,
                     fg=RED if candidate.get("disabled") else GRAY,
                     font=("Segoe UI", 8), wraplength=440, justify="left").pack(
                         anchor="w", padx=8, pady=(0, 6))

            tk.Button(card,
                      text="Use this buddy",
                      command=lambda c=candidate: self._set_manual_buddy(ticket_id, c, keep_source=False),
                      state="disabled" if candidate.get("disabled") else "normal",
                      relief="flat", bd=0,
                      bg="#FF991F" if not candidate.get("disabled") else "#DDE3EA",
                      fg=WHITE if not candidate.get("disabled") else GRAY,
                      font=("Segoe UI", 9, "bold"),
                      padx=10, pady=4, cursor="hand2").pack(anchor="w", padx=8, pady=(0, 8))

        if active_candidates == 0:
            tk.Label(frame,
                     text="All detected buddy accounts are disabled. Use \"Ask reporter\" to request another template account.",
                     bg="#FFF4E5", fg=RED,
                     font=("Segoe UI", 9), wraplength=480, justify="left").pack(
                         anchor="w", padx=10, pady=(0, 8))

    def _fill_disabled_buddy_box(self, frame: tk.Frame, buddy: dict, ticket_id: str):
        """Renders the buddy box in error state when the AD account is disabled."""
        LIGHT_RED = "#FFEBE6"
        DARK_RED   = "#AE2A19"

        frame.configure(bg=LIGHT_RED, highlightbackground=RED, highlightthickness=2)

        tk.Label(frame, text="Buddy account disabled — action required",
                 bg=LIGHT_RED, fg=DARK_RED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(frame, text=self._buddy_caption(buddy), bg=LIGHT_RED, fg=TEXT,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=10, pady=(2, 0))
        source = "Set manually" if buddy.get("author") == "manual" else f"From comment by {buddy['author']}  •  {buddy['date']}"
        tk.Label(frame, text=source, bg=LIGHT_RED, fg=GRAY,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(2, 4))

        # Warning + instructions
        warn = tk.Frame(frame, bg="#FFBDAD",
                        highlightbackground=DARK_RED, highlightthickness=1)
        warn.pack(fill="x", padx=10, pady=(0, 6))
        tk.Label(warn,
                 text="This account is disabled in Active Directory and cannot be used as a template.",
                 bg="#FFBDAD", fg=DARK_RED,
                 font=("Segoe UI", 9, "bold"),
                 wraplength=400, justify="left", anchor="w").pack(anchor="w", padx=8, pady=(6, 2))
        tk.Label(warn,
                 text="1. Click \"Remove disabled buddy\" below to clear this suggestion.\n"
                      "2. Use \"Ask reporter\" to request a valid buddy from the manager or reporter.",
                 bg="#FFBDAD", fg=DARK_RED,
                 font=("Segoe UI", 9),
                 wraplength=400, justify="left", anchor="w").pack(anchor="w", padx=8, pady=(0, 6))

        tk.Button(frame,
                  text="Remove disabled buddy",
                  command=lambda: self._remove_disabled_buddy(ticket_id),
                  relief="flat", bd=0, bg=RED, fg=WHITE,
                  font=("Segoe UI", 9, "bold"),
                  padx=10, pady=4, cursor="hand2").pack(anchor="w", padx=10, pady=(0, 10))

    def _remove_disabled_buddy(self, ticket_id: str):
        if ticket_id is None:
            return
        buddy = self._buddy_hint.get(ticket_id)
        if buddy:
            name = buddy.get("display_name") or buddy.get("name", "")
            if name:
                normalized = unicodedata.normalize("NFC", name)
                self._dismissed_buddy_names[ticket_id] = normalized
                self.storage.set_dismissed_buddy(ticket_id, normalized)
        self._buddy_hint[ticket_id] = None
        self._buddy_fetched.discard(ticket_id)
        self._manual_buddies.discard(ticket_id)
        self.storage.set_manual_buddy(ticket_id, "")  # clear any persisted manual buddy
        self._refresh_buddy_box(ticket_id, None)
        self._update_ask_btn()

    def _draw_buddy_no_result(self, frame: tk.Frame, ticket_id: str):
        for w in frame.winfo_children():
            w.destroy()
        frame.configure(bg="#FFF4E5", highlightbackground="#FF991F")
        tk.Label(frame,
                 text="Buddy not mentioned in comments — consider asking the reporter",
                 bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(6, 2))

        entry_row = tk.Frame(frame, bg="#FFF4E5")
        entry_row.pack(anchor="w", padx=10, pady=(0, 6))
        tk.Label(entry_row, text="Manual buddy:", bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9)).pack(side="left")
        buddy_var = tk.StringVar()
        entry = tk.Entry(entry_row, textvariable=buddy_var, font=("Consolas", 10),
                         relief="solid", bd=1, width=14)
        entry.pack(side="left", padx=6, ipady=2)

        def _set_manual():
            name = buddy_var.get().strip()
            if not name:
                return
            self._set_manual_buddy(ticket_id, {"name": name, "author": "manual", "date": ""})

        tk.Button(entry_row, text="Set as buddy", command=_set_manual,
                  relief="flat", bd=0, bg="#FF991F", fg=WHITE,
                  font=("Segoe UI", 9), padx=8, pady=2, cursor="hand2").pack(side="left")
        entry.bind("<Return>", lambda _: _set_manual())

    def _set_manual_buddy(self, ticket_id: str, buddy_data: dict, keep_source: bool = True):
        # Clear any prior dismissed-buddy state so the new buddy isn't blocked.
        self._dismissed_buddy_names.pop(ticket_id, None)
        self.storage.set_dismissed_buddy(ticket_id, "")

        selected = dict(buddy_data)
        if not keep_source:
            selected["author"] = "manual"
            selected["date"] = ""

        self._buddy_hint[ticket_id] = selected
        self._manual_buddies.add(ticket_id)
        self.storage.set_manual_buddy(ticket_id, selected["name"])
        self._refresh_buddy_box(ticket_id, selected)
        self._update_ask_btn()
        self._update_ad_button()
        threading.Thread(
            target=self._check_buddy_disabled,
            args=(ticket_id, selected), daemon=True,
        ).start()

    def _check_buddy_disabled(self, ticket_id: str, buddy: dict):
        try:
            from ad_automation import get_account_enabled_status, DISABLED_OU_FRAGMENT
            enabled, dn, display_name = get_account_enabled_status(buddy["name"])
            if enabled is None:
                return
            is_dis = not enabled or DISABLED_OU_FRAGMENT.lower() in dn.lower()
        except Exception:
            return
        updated = {**buddy, "disabled": is_dis,
                   "display_name": display_name or buddy.get("display_name") or buddy["name"]}
        self._buddy_hint[ticket_id] = updated
        self.after(0, lambda: self._refresh_buddy_box(ticket_id, updated))

    def _refresh_buddy_box(self, ticket_id: str, buddy: dict | None):
        if self._buddy_box_ticket != ticket_id or not self._buddy_box_frame:
            return
        try:
            if not self._buddy_box_frame.winfo_exists():
                return
        except tk.TclError:
            return
        if buddy:
            self._fill_buddy_box(self._buddy_box_frame, buddy, ticket_id)
        else:
            self._draw_buddy_no_result(self._buddy_box_frame, ticket_id)
        self._update_ask_btn()
        self._update_ad_button()

    # ── Ask reporter ──────────────────────────────────────────────────────────

    def _update_ask_btn(self):
        if not self._ask_btn:
            return
        if self._sel is None or self._sel >= len(self.tickets):
            self._ask_btn.config(state="disabled", bg="#DDE3EA", fg=GRAY)
            return
        tid = self.tickets[self._sel]["id"]
        buddy = self._buddy_hint.get(tid) if tid in self._buddy_fetched else None
        buddy_active = bool(buddy) and (
            (buddy.get("multiple") and any(not c.get("disabled") for c in buddy.get("candidates", [])))
            or (not buddy.get("multiple") and not buddy.get("disabled"))
        )
        if buddy_active:
            self._ask_btn.config(state="disabled", bg="#DDE3EA", fg=GRAY)
        else:
            self._ask_btn.config(state="normal", bg="#6554C0", fg=WHITE)

    def _open_ask_reporter(self):
        if self._sel is None or self._sel >= len(self.tickets):
            return
        ticket = self.tickets[self._sel]

        def on_sent():
            key, tid = ticket["key"], ticket["id"]
            self._comments_cache.pop(key, None)
            self._buddy_hint.pop(tid, None)
            self._buddy_fetched.discard(tid)
            if (self._sel is not None and self._sel < len(self.tickets)
                    and self.tickets[self._sel]["id"] == tid):
                self._show_detail(ticket)

        disabled_buddy = self._dismissed_buddy_names.get(ticket["id"], "")
        AskReporterDialog(self, ticket, self.jira, on_sent=on_sent,
                          disabled_buddy=disabled_buddy)

    # ── Comments ──────────────────────────────────────────────────────────────

    def _fetch_comments(self, issue_key: str, ticket_id: str, box: tk.Text):
        try:
            comments = self.jira.get_comments(issue_key)
            self._comments_cache[issue_key] = comments
            buddy = self._resolve_buddy_from_comments(ticket_id, comments)
            self._buddy_hint[ticket_id] = buddy
            self._buddy_fetched.add(ticket_id)
            self.after(0, lambda: self._populate_comments(box, comments))
            self.after(0, lambda: self._refresh_buddy_box(ticket_id, buddy))
        except Exception as e:
            self.after(0, lambda: self._set_comments_text(box, f"Could not load comments: {e}"))

    def _resolve_buddy_from_comments(self, ticket_id: str, comments: list[dict]) -> dict | None:
        if ticket_id in self._manual_buddies:
            return self._buddy_hint.get(ticket_id)
        return self._resolve_detected_buddies(
            ticket_id, extract_buddies_from_comments(comments)
        )

    def _resolve_detected_buddies(self, ticket_id: str, detected: list[dict]) -> dict | None:
        if not detected:
            return None

        dismissed = unicodedata.normalize(
            "NFC", self._dismissed_buddy_names.get(ticket_id, "")
        )
        resolved: list[dict] = []
        seen: set[str] = set()
        for candidate in detected:
            resolved_candidate = self._resolve_detected_buddy(candidate)
            if not resolved_candidate:
                continue
            if dismissed and self._buddy_matches_dismissed(resolved_candidate, dismissed):
                continue
            key = resolved_candidate["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            resolved.append(resolved_candidate)

        if not resolved:
            return None
        if len(resolved) == 1:
            return resolved[0]
        return {
            "multiple": True,
            "author": resolved[0]["author"],
            "date": resolved[0]["date"],
            "candidates": resolved,
        }

    @staticmethod
    def _buddy_matches_dismissed(candidate: dict, dismissed_name: str) -> bool:
        dismissed_folded = dismissed_name.casefold()
        names = {
            unicodedata.normalize("NFC", candidate.get("name", "")).casefold(),
            unicodedata.normalize("NFC", candidate.get("display_name", "")).casefold(),
        }
        return dismissed_folded in names

    @staticmethod
    def _resolve_detected_buddy(candidate: dict) -> dict | None:
        try:
            from ad_automation import (
                DISABLED_OU_FRAGMENT,
                find_user_accounts_by_name,
                get_account_enabled_status,
            )
        except Exception:
            return None

        if is_sam_account(candidate["name"]):
            try:
                enabled, dn, display_name = get_account_enabled_status(candidate["name"])
            except Exception:
                return None
            if enabled is None:
                return None
            is_dis = not enabled or DISABLED_OU_FRAGMENT.lower() in dn.lower()
            return {
                **candidate,
                "disabled": is_dis,
                "display_name": display_name or candidate["name"],
            }

        try:
            original_name = unicodedata.normalize("NFC", candidate["name"])
            accounts = find_user_accounts_by_name(original_name)
        except Exception:
            return None

        enabled_accounts = [a for a in accounts if a["enabled"]]
        match = enabled_accounts or accounts
        if not match:
            return None

        selected = match[0]
        is_dis = not selected["enabled"] or DISABLED_OU_FRAGMENT.lower() in selected["dn"].lower()
        return {
            **candidate,
            "name": selected["username"],
            "disabled": is_dis,
            "display_name": original_name,
        }

    def _populate_comments(self, box: tk.Text, comments: list[dict]):
        if not comments:
            self._set_comments_text(box, "No comments.")
            return
        parts = []
        for c in comments:
            parts.append(f"[{c['created']}]  {c['author']}\n{c['body']}")
        self._set_comments_text(box, "\n\n─────────────────────────────\n\n".join(parts))

    @staticmethod
    def _set_comments_text(box: tk.Text, text: str):
        try:
            box.config(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", text)
            box.config(state="disabled")
        except tk.TclError:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_jira(self):
        if self._sel is not None and self._sel < len(self.tickets):
            webbrowser.open(self.tickets[self._sel]["url"])

    def _open_ad_setup(self):
        if self._sel is None or self._sel >= len(self.tickets):
            return
        ticket = self.tickets[self._sel]
        if self.storage.ad_setup_done(ticket["id"]):
            messagebox.showinfo("AD setup already completed",
                                "AD setup is already marked as completed for this joiner.",
                                parent=self)
            return
        from ad_ui import ADSetupWindow
        buddy_info = self._buddy_hint.get(ticket["id"])
        buddy_name = buddy_info["name"] if buddy_info and not buddy_info.get("multiple") else ""
        ADSetupWindow(
            self,
            ticket,
            storage=self.storage,
            on_completed=lambda: self._ad_setup_completed(ticket),
            buddy_hint=buddy_name,
        )

    def _do_refresh(self):
        self._status.set("Refreshing...")
        self.on_refresh()

    def _backup_data(self):
        self._save_current_notes()
        try:
            path = self.storage.backup_tasks()
            self._status.set(f"Backup saved: {path}")
            messagebox.showinfo("Backup saved", f"Notes and checklist progress were backed up to:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Backup failed", str(e), parent=self)

    def update_tickets(self, tickets: list):
        self.tickets = tickets
        self._refresh_list()
        self._status.set(f"Loaded {len(tickets)} ticket(s).")
        if self._sel is not None and self._sel < len(tickets):
            self._show_detail(tickets[self._sel])
        self._update_ad_button()
        self._update_ask_btn()

    def _show_ad_setup_summary(self, t: dict):
        info = self.storage.get_ad_setup(t["id"])
        if not info:
            return

        box = tk.Frame(self._detail, bg="#E7F4EC", highlightbackground="#B8E0C7",
                       highlightthickness=1)
        box.pack(fill="x", padx=24, pady=(2, 12))
        tk.Label(box, text="AD setup completed", bg="#E7F4EC", fg=GREEN,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))

        details = []
        if info.get("completed_at"):
            details.append(f"Completed: {info['completed_at']}")
        if info.get("status"):
            details.append(f"Result: {info['status']}")
        if info.get("account"):
            details.append(f"Account: {info['account']}")
        if info.get("email"):
            details.append(f"Email: {info['email']}")
        if info.get("scenario"):
            details.append(f"Case: {str(info['scenario']).replace('_', ' ')}")
        if info.get("groups_count") not in (None, ""):
            details.append(f"Groups added: {info['groups_count']}")

        details_frame = tk.Frame(box, bg="#E7F4EC")
        details_frame.pack(fill="x", padx=10, pady=(0, 8))
        for detail in details:
            tk.Label(details_frame, text=detail, bg="#E7F4EC", fg=TEXT,
                     font=("Segoe UI", 9), anchor="w", justify="left").pack(
                         anchor="w", fill="x", pady=1)

        if info.get("target_ou"):
            tk.Label(box, text=f"Target folder: {info['target_ou']}", bg="#E7F4EC", fg=GRAY,
                     font=("Segoe UI", 8), wraplength=620, justify="left").pack(
                         anchor="w", padx=10, pady=(0, 8))

    def _update_ad_button(self):
        if not self._ad_btn:
            return
        if self._sel is None or self._sel >= len(self.tickets):
            self._ad_btn.config(state="disabled", text="AD Setup", bg="#DDE3EA", fg=GRAY)
            return

        ticket = self.tickets[self._sel]
        if self.storage.ad_setup_done(ticket["id"]):
            self._ad_btn.config(state="disabled", text="AD done", bg="#DDE3EA", fg=GRAY)
        else:
            self._ad_btn.config(state="normal", text="AD Setup", bg="#00875A", fg=WHITE)

    def _ad_setup_completed(self, ticket: dict):
        self.storage.set(ticket["id"], AD_TASK_INDEX, True, len(TASKS))
        self._refresh_list()
        if self._sel is not None and self._sel < len(self.tickets):
            self._listbox.selection_set(self._sel)
        self._show_detail(ticket)
        self._status.set("AD setup marked as completed.")

    def _sync_ad_task(self, ticket_id: str):
        if not self.storage.ad_setup_done(ticket_id):
            return
        state = self.storage.get(ticket_id, len(TASKS))
        if not state[AD_TASK_INDEX]:
            self.storage.set(ticket_id, AD_TASK_INDEX, True, len(TASKS))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_btn(parent, text, cmd, fg, bg):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                         relief="flat", bd=0, font=("Segoe UI", 9),
                         padx=10, pady=4, cursor="hand2",
                         activebackground=ACCENT, activeforeground=WHITE)


class SetupDialog(tk.Toplevel):
    """First-run / settings configuration dialog. Result in .result dict."""

    DEFAULTS = {
        "jira_url":              "https://girteka.atlassian.net",
        "email":                 "",
        "api_token":             "",
        "jql":                   'assignee = currentUser() AND issuetype = "SF: Employee onboarding" AND status in (Open, "In Progress", Pending)',
        "date_field":            "customfield_10980",
        "remind_days_before":    "3",
        "check_interval_minutes": "30",
    }

    def __init__(self, parent, prefill: dict | None = None):
        super().__init__(parent)
        self.result = None
        self.title("Jira Reminders - Settings")
        self.geometry("580x520")
        self.resizable(False, True)
        self.configure(bg=BG)
        self.grab_set()

        cfg = {**self.DEFAULTS, **(prefill or {})}
        self._vars = {k: tk.StringVar(value=str(v)) for k, v in cfg.items()}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        # Fixed header
        tk.Label(self, text="  Jira Reminders - Settings", bg=ACCENT, fg=WHITE,
                 font=("Segoe UI", 13, "bold")).pack(fill="x", ipady=10)

        # Fixed bottom bar with buttons, packed before the canvas so it's always visible
        btm = tk.Frame(self, bg=BG, bd=0)
        btm.pack(side="bottom", fill="x", padx=24, pady=10)
        self._msg = tk.Label(btm, text="", bg=BG, fg=GRAY, font=("Segoe UI", 9))
        self._msg.pack(side="bottom", pady=(4, 0))
        tk.Button(btm, text="Save & Start", command=self._save,
                  relief="flat", bd=0, bg=ACCENT, fg=WHITE,
                  font=("Segoe UI", 9, "bold"), padx=14, pady=5).pack(side="right")
        tk.Button(btm, text="Test Connection", command=self._test,
                  relief="flat", bd=0, bg="#DEEBFF", fg=ACCENT,
                  font=("Segoe UI", 9), padx=10, pady=5).pack(side="left")

        # Scrollable canvas for form fields
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        form = tk.Frame(canvas, bg=BG)
        form_id = canvas.create_window((0, 0), window=form, anchor="nw")

        def _on_frame_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(form_id, width=event.width)

        form.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        fields = [
            ("Jira URL",               "jira_url",              False,
             "https://girteka.atlassian.net"),
            ("Email",                  "email",                 False,
             "Your Atlassian account email"),
            ("API Token",              "api_token",             True,
             "Create at id.atlassian.com -> Security -> API tokens"),
            ("JQL Query",              "jql",                   False,
             'Filter for onboarding tickets - issue type is "SF: Employee onboarding"'),
            ("Start date field",       "date_field",            False,
             "customfield_10980  (do not change unless Jira schema changed)"),
            ("Remind N days before",   "remind_days_before",    False,
             "3 = notify 3 days ahead and on the start day"),
            ("Check every N minutes",  "check_interval_minutes", False,
             "Background poll interval (30 is a good default)"),
        ]

        for label, key, secret, hint in fields:
            tk.Label(form, text=label, bg=BG, fg=TEXT,
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x",
                     padx=24, pady=(8, 0))
            tk.Entry(form, textvariable=self._vars[key],
                     show="*" if secret else "",
                     relief="solid", bd=1, font=("Segoe UI", 10)).pack(
                     fill="x", padx=24, ipady=4)
            tk.Label(form, text=hint, bg=BG, fg=GRAY,
                     font=("Segoe UI", 8)).pack(fill="x", padx=24)

    def _collect(self) -> dict:
        return {
            "jira_url":               self._vars["jira_url"].get().strip().rstrip("/"),
            "email":                  self._vars["email"].get().strip(),
            "api_token":              self._vars["api_token"].get().strip(),
            "jql":                    self._vars["jql"].get().strip(),
            "date_field":             self._vars["date_field"].get().strip() or "customfield_10980",
            "remind_days_before":     int(self._vars["remind_days_before"].get() or 3),
            "check_interval_minutes": int(self._vars["check_interval_minutes"].get() or 30),
        }

    def _test(self):
        from jira_client import JiraClient
        cfg = self._collect()
        self._msg.config(text="Connecting...", fg=GRAY)
        self.update()
        try:
            name = JiraClient(cfg["jira_url"], cfg["email"], cfg["api_token"]).test_connection()
            self._msg.config(text=f"Connected as: {name}", fg=GREEN)
        except Exception as e:
            self._msg.config(text=f"Error: {e}", fg=RED)

    def _save(self):
        try:
            cfg = self._collect()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e), parent=self)
            return
        self.result = cfg
        self.destroy()


class AskReporterDialog(tk.Toplevel):
    _TEMPLATE = (
        "Hello, @manager,\n\n"
        "Could you please let us know the name of an existing employee with similar "
        "access rights that we can use as a template for {name}'s account setup? "
        "Also, please specify any additional applications, mailboxes, or system access "
        "required.\n\n"
        "Thank you."
    )
    _TEMPLATE_DISABLED_BUDDY = (
        "Hello, @manager,\n\n"
        "{buddy_name} is no longer working, so we cannot use them as a buddy, because "
        "the account is disabled. Could you please let us know the name of an existing "
        "employee with similar access rights that we can use as a template for {name}'s "
        "account setup? Also, please specify any additional applications, mailboxes, or "
        "system access required.\n\n"
        "Thank you."
    )

    def __init__(self, parent, ticket: dict, jira_client, on_sent,
                 disabled_buddy: str = ""):
        super().__init__(parent)
        self._ticket         = ticket
        self._jira           = jira_client
        self._on_sent        = on_sent
        self._disabled_buddy = disabled_buddy
        self._mention_map: dict[str, str] = {}
        self.title(f"Ask reporter — {ticket.get('key', '')}")
        self.geometry("560x400")
        self.resizable(False, True)
        self.configure(bg=BG)
        self.grab_set()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        threading.Thread(target=self._resolve_mentions, daemon=True).start()

    def _resolve_mentions(self):
        manager_mention  = None
        reporter_mention = None

        manager = self._ticket.get("manager", "").strip()
        if manager:
            try:
                manager_mention = self._jira.search_user(manager)
            except Exception:
                pass

        if self._ticket.get("reporter_id"):
            reporter_mention = {
                "id":   self._ticket["reporter_id"],
                "text": f"@{self._ticket.get('reporter_name', 'Reporter')}",
            }

        # Build ordered greeting list; skip reporter if same account as manager
        greeting: list[dict] = []
        if manager_mention:
            greeting.append(manager_mention)
        if reporter_mention:
            if not manager_mention or reporter_mention["text"] != manager_mention["text"]:
                greeting.append(reporter_mention)

        self._mention_map = {m["text"]: m["id"] for m in greeting}

        def _update():
            current = self._text.get("1.0", "end-1c")
            if greeting:
                substitution = ", ".join(m["text"] for m in greeting)
                new_text = current.replace("@manager", substitution, 1)
            else:
                new_text = current
            if new_text != current:
                self._text.delete("1.0", "end")
                self._text.insert("1.0", new_text)

            if self._mention_map:
                label = "Will tag: " + "   ".join(self._mention_map)
                color = ACCENT
            else:
                label = "No Jira accounts found to tag"
                color = GRAY
            self._tag_label.config(text=label, fg=color)

        try:
            self.after(0, _update)
        except Exception:
            pass

    def _build(self):
        tk.Label(self, text="  Post comment to Jira", bg=ACCENT, fg=WHITE,
                 font=("Segoe UI", 11, "bold")).pack(fill="x", ipady=8)
        tk.Label(self,
                 text=f"  {self._ticket['key']}  —  {self._ticket.get('name', '')}",
                 bg=BG, fg=GRAY, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(10, 2))

        self._tag_label = tk.Label(self, text="Resolving mentions…",
                                   bg=BG, fg=GRAY, font=("Segoe UI", 8, "italic"))
        self._tag_label.pack(anchor="w", padx=20, pady=(0, 6))

        self._text = tk.Text(self, height=10, relief="solid", bd=1,
                             font=("Segoe UI", 10), bg=WHITE, fg=TEXT,
                             wrap="word", padx=8, pady=6)
        if self._disabled_buddy:
            body = self._TEMPLATE_DISABLED_BUDDY.format(
                buddy_name=self._disabled_buddy,
                name=self._ticket.get("name", "the new joiner"),
            )
        else:
            body = self._TEMPLATE.format(name=self._ticket.get("name", "the new joiner"))
        self._text.insert("1.0", body)
        self._text.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        btm = tk.Frame(self, bg=BG)
        btm.pack(fill="x", padx=20, pady=(0, 14))
        self._msg = tk.Label(btm, text="", bg=BG, fg=GRAY, font=("Segoe UI", 9))
        self._msg.pack(side="bottom", anchor="w", pady=(4, 0))
        tk.Button(btm, text="Cancel", command=self.destroy,
                  relief="flat", bd=0, bg="#DDE3EA", fg=TEXT,
                  font=("Segoe UI", 9), padx=12, pady=4).pack(side="right")
        tk.Button(btm, text="Post comment", command=self._send,
                  relief="flat", bd=0, bg=ACCENT, fg=WHITE,
                  font=("Segoe UI", 9, "bold"), padx=12, pady=4).pack(
                      side="right", padx=(0, 8))

    def _send(self):
        text = self._text.get("1.0", "end-1c").strip()
        if not text:
            return
        self._msg.config(text="Posting…", fg=GRAY)
        self.update()
        try:
            self._jira.post_comment(self._ticket["key"], text, self._mention_map or None)
            self._msg.config(text="Comment posted!", fg=GREEN)
            self.after(800, lambda: (self._on_sent(), self.destroy()))
        except Exception as e:
            self._msg.config(text=f"Error: {e}", fg=RED)
