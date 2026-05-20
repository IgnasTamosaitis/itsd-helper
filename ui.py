import os
import threading
import tkinter as tk
from tkinter import messagebox
import webbrowser
from datetime import date
import unicodedata

from jira_client import extract_buddies_from_comments, is_sam_account
from leaver_document import generate_leaver_return_document
from ad_automation import find_user_accounts, classify_scenario

TASKS = [
    "Active Directory account setup",
    "Axapta account import/creation",
    "Hardware preparation (laptop, phone, headphones)",
    "Assign hardware & licenses in Snipe-IT",
    "SIM card activation and assignment",
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
INPUT_BORDER = "#C7D1DB"
INPUT_BG = "#FFFFFF"
ACTION_BTN_WIDTH = 20
PRIORITY_COMPANY_COLOR = RED


class MainWindow(tk.Toplevel):
    def __init__(self, parent, tickets: list, storage, jira_client, on_refresh,
                 leaver_tickets: list = None, on_leaver_refresh=None, snipeit=None):
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
        self._ad_joiner_checks: set = set()      # ticket_ids with in-flight AD joiner-type checks
        self._load_manual_buddies()
        self._load_dismissed_buddies()

        # Leavers state
        self.leaver_tickets: list[dict] = leaver_tickets or []
        self.on_leaver_refresh = on_leaver_refresh
        self._snipeit = snipeit
        self._leaver_sel: int | None = None
        self._leaver_listbox: tk.Listbox | None = None
        self._leaver_hint: tk.Label | None = None
        self._leaver_detail: tk.Frame | None = None
        self._leaver_detail_canvas: tk.Canvas | None = None
        self._leaver_detail_sb: tk.Scrollbar | None = None
        self._leaver_detail_wid = None
        self._leaver_open_btn: tk.Button | None = None
        self._add_accountants_btn: tk.Button | None = None
        self._leaver_doc_btn: tk.Button | None = None
        self._leaver_comments_cache: dict = {}
        self._leaver_comment_box: tk.Text | None = None
        self._leaver_comment_ticket_id: str | None = None
        self._leaver_laptop_frame: tk.Frame | None = None
        self._leaver_laptop_fetch_for: str = ""   # ticket_id of in-flight fetch
        self._leaver_laptop_info: dict | None = None

        self.title("ITSD Jira Helper")
        self.geometry("980x620")
        self.resizable(True, True)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self._build()
        self._refresh_list()
        self._update_ad_button()
        self._refresh_leavers_list()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Top bar ───────────────────────────────────────────────────────────────
        bar = tk.Frame(self, bg=ACCENT, height=44)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="  ITSD Jira Helper", bg=ACCENT, fg=WHITE,
                 font=("Segoe UI", 13, "bold")).pack(side="left", pady=10)
        self._make_btn(bar, "Refresh", self._do_refresh, WHITE, ACCENT).pack(
            side="right", padx=10, pady=8)

        # ── Tab strip ─────────────────────────────────────────────────────────────
        tab_strip = tk.Frame(self, bg=WHITE, height=38)
        self._tab_strip = tab_strip
        tab_strip.pack(fill="x")
        tab_strip.pack_propagate(False)
        self._tab_btns: dict[str, tk.Button] = {}
        for key, label in [("joiners", "New Joiners"), ("leavers", "Leavers")]:
            btn = tk.Button(
                tab_strip, text=label,
                command=lambda k=key: self._switch_tab(k),
                relief="flat", bd=0,
                font=("Segoe UI", 10),
                padx=20, pady=0,
                cursor="hand2",
                activebackground=ACCENT, activeforeground=WHITE,
            )
            btn.pack(side="left", fill="y")
            self._tab_btns[key] = btn
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── Tab content frames ────────────────────────────────────────────────────
        self._joiners_tab_frame = tk.Frame(self, bg=BG)
        self._leavers_tab_frame = tk.Frame(self, bg=BG)
        self._build_joiners_tab(self._joiners_tab_frame)
        self._build_leavers_tab(self._leavers_tab_frame)

        self._active_tab: str = ""
        self._switch_tab("joiners")

    def show_update_banner(self, version: str, on_install) -> None:
        if getattr(self, "_update_banner", None):
            return
        BANNER_BG = "#FFFAE6"
        BANNER_FG = "#172B4D"
        AMBER     = "#FF991F"

        banner = tk.Frame(self, bg=BANNER_BG, height=34)
        banner.pack(fill="x", before=self._tab_strip)
        banner.pack_propagate(False)
        self._update_banner = banner

        tk.Label(
            banner,
            text=f"  ⬆  Version {version} is available — install and restart to update.",
            bg=BANNER_BG, fg=BANNER_FG,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(8, 0))

        def _dismiss():
            banner.destroy()
            self._update_banner = None

        def _install():
            _dismiss()
            on_install()

        tk.Button(
            banner, text="Install & restart",
            bg=AMBER, fg=WHITE, relief="flat", bd=0,
            font=("Segoe UI", 9, "bold"), padx=10, cursor="hand2",
            activebackground="#E08010", activeforeground=WHITE,
            command=_install,
        ).pack(side="right", padx=(4, 8), pady=4)

        tk.Button(
            banner, text="×",
            bg=BANNER_BG, fg=GRAY, relief="flat", bd=0,
            font=("Segoe UI", 11), padx=6, cursor="hand2",
            activebackground=BANNER_BG, activeforeground=TEXT,
            command=_dismiss,
        ).pack(side="right", pady=4)

    def _switch_tab(self, key: str):
        if self._active_tab == key:
            return
        self._active_tab = key
        self._joiners_tab_frame.pack_forget()
        self._leavers_tab_frame.pack_forget()
        frame = self._joiners_tab_frame if key == "joiners" else self._leavers_tab_frame
        frame.pack(fill="both", expand=True)
        for k, btn in self._tab_btns.items():
            if k == key:
                btn.config(bg=ACCENT, fg=WHITE, font=("Segoe UI", 10, "bold"))
            else:
                btn.config(bg=WHITE, fg=GRAY, font=("Segoe UI", 10))

    def _build_joiners_tab(self, parent: tk.Frame):
        # Bottom bar — packed first so it anchors to bottom before body expands
        btm = tk.Frame(parent, bg="#EEF2F7", height=46)
        btm.pack(fill="x", side="bottom")
        btm.pack_propagate(False)
        self._status = tk.StringVar(value="")
        tk.Label(btm, textvariable=self._status, bg="#EEF2F7", fg=GRAY,
                 font=("Segoe UI", 9)).pack(side="left", padx=12)
        self._make_btn(btm, "Open in Jira", self._open_jira, WHITE, ACCENT,
                       width=ACTION_BTN_WIDTH).pack(
            side="right", padx=10, pady=8)
        self._ad_btn = self._make_btn(btm, "AD Setup", self._open_ad_setup, WHITE, "#00875A",
                                      width=ACTION_BTN_WIDTH)
        self._ad_btn.pack(side="right", padx=(0, 4), pady=8)
        self._make_btn(btm, "Back up data", self._backup_data, ACCENT, SOFT_BLUE,
                       width=ACTION_BTN_WIDTH).pack(
            side="right", padx=(0, 4), pady=8)
        self._ask_btn = self._make_btn(btm, "Ask reporter", self._open_ask_reporter,
                                       WHITE, "#6554C0", width=ACTION_BTN_WIDTH)
        self._ask_btn.pack(side="right", padx=(0, 4), pady=8)

        # Body: left (list) + right (detail)
        body = tk.Frame(parent, bg=BG)
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
            activestyle="none", highlightthickness=0, exportselection=False,
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
        self._bind_detail_scroll(self._detail)

    def _build_leavers_tab(self, parent: tk.Frame):
        # Bottom bar — packed first
        btm = tk.Frame(parent, bg="#EEF2F7", height=46)
        btm.pack(fill="x", side="bottom")
        btm.pack_propagate(False)
        self._leavers_status = tk.StringVar(value="")
        tk.Label(btm, textvariable=self._leavers_status, bg="#EEF2F7", fg=GRAY,
                 font=("Segoe UI", 9)).pack(side="left", padx=12)
        self._leaver_open_btn = self._make_btn(btm, "Open in Jira",
                                               self._leaver_open_jira, WHITE, ACCENT,
                                               width=ACTION_BTN_WIDTH)
        self._leaver_open_btn.pack(side="right", padx=10, pady=8)
        self._leaver_doc_btn = self._make_btn(btm, "Generate return act",
                                              self._generate_leaver_return_act,
                                              WHITE, GREEN, width=ACTION_BTN_WIDTH)
        self._leaver_doc_btn.pack(side="right", padx=(0, 4), pady=8)
        self._add_accountants_btn = self._make_btn(btm, "Add accountants",
                                                   self._leaver_add_accountants,
                                                   WHITE, "#FF991F",
                                                   width=ACTION_BTN_WIDTH)
        self._add_accountants_btn.pack(side="right", padx=(0, 4), pady=8)

        # Body
        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True)

        # Left panel — list
        left = tk.Frame(body, bg=WHITE, width=420)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Upcoming leavers", bg=WHITE, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(14, 6))
        self._leaver_listbox = tk.Listbox(
            left, selectmode="single", relief="flat", bd=0,
            bg=WHITE, fg=TEXT, font=("Segoe UI", 10),
            selectbackground=SOFT_BLUE, selectforeground=ACCENT,
            activestyle="none", highlightthickness=0, exportselection=False,
        )
        self._leaver_listbox.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._leaver_listbox.bind("<<ListboxSelect>>", self._on_leaver_select)

        # Right panel — detail
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        self._leaver_hint = tk.Label(right, text="Select a leaver to view details",
                                     bg=BG, fg=GRAY, font=("Segoe UI", 11))
        self._leaver_hint.place(relx=0.5, rely=0.5, anchor="center")

        self._leaver_detail_sb = tk.Scrollbar(right, orient="vertical")
        self._leaver_detail_canvas = tk.Canvas(right, bg=BG, highlightthickness=0,
                                               yscrollcommand=self._leaver_detail_sb.set)
        self._leaver_detail_sb.configure(command=self._leaver_detail_canvas.yview)
        self._leaver_detail = tk.Frame(self._leaver_detail_canvas, bg=BG)
        self._leaver_detail_wid = self._leaver_detail_canvas.create_window(
            (0, 0), window=self._leaver_detail, anchor="nw")
        self._leaver_detail.bind("<Configure>", lambda e: self._leaver_detail_canvas.configure(
            scrollregion=self._leaver_detail_canvas.bbox("all")))
        self._leaver_detail_canvas.bind("<Configure>", lambda e: self._leaver_detail_canvas.itemconfig(
            self._leaver_detail_wid, width=e.width))
        self._bind_leaver_detail_scroll(self._leaver_detail)

    # ── Leavers list ──────────────────────────────────────────────────────────

    def _refresh_leavers_list(self):
        if not self._leaver_listbox:
            return
        self._leaver_listbox.delete(0, "end")
        today = date.today()
        visible_tickets = []
        hidden_statuses = {"done", "closed", "resolved", "completed",
                           "declined", "cancelled", "canceled", "rejected", "withdrawn"}
        for t in self.leaver_tickets:
            status = str(t.get("status", "")).strip().lower()
            last_day = t.get("last_day")
            if status in hidden_statuses:
                continue
            if last_day and last_day < today:
                continue
            visible_tickets.append(t)
        self.leaver_tickets = visible_tickets

        for i, t in enumerate(self.leaver_tickets):
            ld    = t.get("last_day")
            color = TEXT

            if ld:
                delta = (ld - today).days
                if delta < 0:
                    date_tag = f"left {-delta}d ago"
                    color = GRAY
                elif delta == 0:
                    date_tag = "LAST DAY TODAY"
                    color = RED
                elif delta == 1:
                    date_tag = "last day TOMORROW"
                    color = RED
                elif delta <= 7:
                    date_tag = f"leaves in {delta}d"
                    color = GREEN
                else:
                    date_tag = f"{ld.strftime('%b %d')} ({delta}d)"
            else:
                date_tag = "no date"

            summary = (t.get("summary") or "").strip()
            summary_tag = f"  {summary}  |" if summary else ""
            label = f"  {t['key']}{summary_tag}  {t['name']}  [{date_tag}]"
            self._leaver_listbox.insert("end", label)
            self._leaver_listbox.itemconfig(i, fg=color)

        if not self.leaver_tickets:
            self._leaver_listbox.insert("end", "  No leaver tickets found")
            self._leavers_status.set("No leaver tickets found.")

    def _on_leaver_select(self, _=None):
        sel = self._leaver_listbox.curselection()
        if not sel or sel[0] >= len(self.leaver_tickets):
            return
        self._leaver_sel = sel[0]
        self._show_leaver_detail(self.leaver_tickets[self._leaver_sel])

    # ── Leavers detail ────────────────────────────────────────────────────────

    def _show_leaver_detail(self, t: dict):
        self._leaver_hint.place_forget()

        for w in self._leaver_detail.winfo_children():
            w.destroy()
        self._leaver_comment_box = None
        self._leaver_comment_ticket_id = None

        self._leaver_detail_sb.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne", width=16)
        self._leaver_detail_canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0, width=-16)
        self._leaver_detail_canvas.yview_moveto(0.0)

        # Name + badge
        name_row = tk.Frame(self._leaver_detail, bg=BG)
        name_row.pack(anchor="w", padx=24, pady=(20, 2))
        tk.Label(name_row, text=t["name"], bg=BG, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(name_row, text="Leaver", bg=RED, fg=WHITE,
                 font=("Segoe UI", 9, "bold"), padx=8, pady=3,
                 relief="flat").pack(side="left", padx=(12, 0))

        if t.get("summary"):
            tk.Label(self._leaver_detail, text=t["summary"], bg=BG, fg=GRAY,
                     font=("Segoe UI", 9), wraplength=520, justify="left").pack(
                         anchor="w", padx=24, pady=(0, 6))

        # Last day date
        today = date.today()
        ld = t.get("last_day")
        if ld:
            delta = (ld - today).days
            if delta < 0:
                date_text  = f"{ld}  (left {-delta} day(s) ago)"
                date_color = GRAY
            elif delta == 0:
                date_text  = f"{ld}  — LAST DAY TODAY"
                date_color = RED
            elif delta <= 3:
                date_text  = f"{ld}  — leaves in {delta} day(s)"
                date_color = "#FF991F"
            else:
                date_text  = f"{ld}  — in {delta} day(s)"
                date_color = TEXT
        else:
            date_text  = "Last day: not set"
            date_color = GRAY

        tk.Label(self._leaver_detail, text=date_text, bg=BG, fg=date_color,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=24, pady=(0, 2))

        meta_parts = []
        if t.get("job_title"):   meta_parts.append(t["job_title"])
        if t.get("department"):  meta_parts.append(t["department"])
        if t.get("company"):     meta_parts.append(t["company"])
        if t.get("status"):      meta_parts.append(t["status"])
        if meta_parts:
            tk.Label(self._leaver_detail, text="  |  ".join(meta_parts),
                     bg=BG, fg=GRAY, font=("Segoe UI", 9),
                     wraplength=500, justify="left").pack(anchor="w", padx=24, pady=(0, 2))

        tk.Label(self._leaver_detail, text=t["key"], bg=BG, fg=GRAY,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=24, pady=(0, 10))

        # Laptop card (auto-fetched from Snipe-IT)
        self._leaver_laptop_frame = tk.Frame(
            self._leaver_detail, bg=SOFT_BLUE,
            highlightbackground=ACCENT, highlightthickness=1)
        self._leaver_laptop_frame.pack(fill="x", padx=24, pady=(0, 10))
        self._leaver_laptop_info = None
        self._leaver_laptop_fetch_for = t["id"]
        self._draw_laptop_card_loading()
        if self._snipeit:
            threading.Thread(
                target=self._leaver_fetch_laptop,
                args=(t,),
                daemon=True,
            ).start()
        else:
            self._draw_laptop_card_no_snipeit()

        tk.Frame(self._leaver_detail, bg=BORDER, height=1).pack(fill="x", padx=24, pady=(0, 10))

        # Post comment
        tk.Label(self._leaver_detail, text="Post comment", bg=BG, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 4))
        comment_box = self._make_text_box(self._leaver_detail, height=6)
        comment_box.pack(fill="x", padx=24, pady=(0, 4))
        self._leaver_comment_box = comment_box
        self._leaver_comment_ticket_id = t["id"]
        self._bind_text_widget_scroll(comment_box, self._leaver_detail_canvas)

        post_row = tk.Frame(self._leaver_detail, bg=BG)
        post_row.pack(anchor="e", padx=24, pady=(0, 8))
        self._leaver_post_status = tk.Label(post_row, text="", bg=BG, fg=GRAY,
                                            font=("Segoe UI", 9))
        self._leaver_post_status.pack(side="left", padx=(0, 10))
        self._make_btn(post_row, "Post buyout template",
                       self._post_current_laptop_template,
                       WHITE, GREEN, width=ACTION_BTN_WIDTH).pack(side="right", padx=(0, 8))
        self._make_btn(post_row, "Post comment",
                       lambda tid=t["id"], key=t["key"]: self._leaver_post_comment(tid, key),
                       WHITE, ACCENT, width=ACTION_BTN_WIDTH).pack(side="right")

        tk.Frame(self._leaver_detail, bg=BORDER, height=1).pack(fill="x", padx=24, pady=(4, 8))

        # Comments
        tk.Label(self._leaver_detail, text="Jira comments", bg=BG, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 4))

        comments_frame = tk.Frame(self._leaver_detail, bg=BG)
        comments_frame.pack(fill="x", padx=24, pady=(0, 16))
        comments_frame.columnconfigure(0, weight=1)

        comments_box = self._make_text_box(comments_frame, height=12, readonly=True,
                                           font=("Segoe UI", 9))
        comments_sb = tk.Scrollbar(comments_frame, orient="vertical",
                                   command=comments_box.yview)
        comments_box.configure(yscrollcommand=comments_sb.set)
        comments_box.grid(row=0, column=0, sticky="ew")
        comments_sb.grid(row=0, column=1, sticky="ns")
        self._bind_text_widget_scroll(comments_box, self._leaver_detail_canvas)

        if t["key"] in self._leaver_comments_cache:
            self._populate_comments(comments_box, self._leaver_comments_cache[t["key"]])
        else:
            self._set_comments_text(comments_box, "Loading...")

        threading.Thread(
            target=self._leaver_fetch_comments,
            args=(t["key"], comments_box),
            daemon=True,
        ).start()

        self._bind_leaver_detail_scroll(self._leaver_detail)
        self._leavers_status.set(f"  {t['name']}")
        self._update_leaver_open_btn()

    def _bind_leaver_detail_scroll(self, widget):
        widget.bind("<MouseWheel>",
            lambda e: self._scroll_canvas_from_event(self._leaver_detail_canvas, e))
        for child in widget.winfo_children():
            if isinstance(child, tk.Text):
                continue
            self._bind_leaver_detail_scroll(child)

    # ── Laptop card ───────────────────────────────────────────────────────────

    def _draw_laptop_card_loading(self):
        f = self._leaver_laptop_frame
        for w in f.winfo_children(): w.destroy()
        f.configure(bg=SOFT_BLUE, highlightbackground=ACCENT)
        tk.Label(f, text="Laptop (Snipe-IT)", bg=SOFT_BLUE, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(f, text="Searching inventory...", bg=SOFT_BLUE, fg=GRAY,
                 font=("Segoe UI", 9, "italic")).pack(anchor="w", padx=10, pady=(2, 8))

    def _draw_laptop_card_no_snipeit(self):
        f = self._leaver_laptop_frame
        for w in f.winfo_children(): w.destroy()
        f.configure(bg="#FFF4E5", highlightbackground="#FF991F")
        tk.Label(f, text="Laptop (Snipe-IT)", bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(f, text="Add Snipe-IT credentials in Settings to auto-fetch laptop details.",
                 bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(2, 8))

    def _draw_laptop_card_found(self, laptop: dict):
        f = self._leaver_laptop_frame
        for w in f.winfo_children(): w.destroy()
        f.configure(bg="#E7F4EC", highlightbackground="#B8E0C7")
        tk.Label(f, text="Laptop (Snipe-IT)", bg="#E7F4EC", fg=GREEN,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))

        info_row = tk.Frame(f, bg="#E7F4EC")
        info_row.pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(info_row, text=f"Model:  {laptop['model']}", bg="#E7F4EC", fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(info_row, text=f"SN:       {laptop['serial']}", bg="#E7F4EC", fg=TEXT,
                 font=("Segoe UI", 10)).pack(anchor="w")

        btn_row = tk.Frame(f, bg="#E7F4EC")
        btn_row.pack(anchor="w", padx=10, pady=(0, 8))
        self._make_btn(btn_row, "Fill comment template",
                       lambda: self._fill_laptop_comment_template(laptop),
                       WHITE, GREEN, width=ACTION_BTN_WIDTH).pack(side="left")
        self._make_btn(btn_row, "Post template comment",
                       self._post_current_laptop_template,
                       WHITE, ACCENT, width=ACTION_BTN_WIDTH).pack(side="left", padx=(8, 0))

    def _draw_laptop_card_not_found(self):
        f = self._leaver_laptop_frame
        for w in f.winfo_children(): w.destroy()
        f.configure(bg="#FFF4E5", highlightbackground="#FF991F")
        tk.Label(f, text="Laptop (Snipe-IT)", bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(f, text="No laptop found in inventory for this person.",
                 bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=10, pady=(2, 8))

    def _leaver_fetch_laptop(self, t: dict):
        """Background: search Snipe-IT for the leaver's laptop and update the card."""
        ticket_id = t["id"]
        try:
            user = self._snipeit.find_user(t.get("first_name", ""), t.get("last_name", ""))
            if not user:
                laptop = None
            else:
                laptop = self._snipeit.get_laptop(user["id"])
        except Exception:
            laptop = None

        def _update():
            if self._leaver_laptop_fetch_for != ticket_id:
                return  # user switched tickets while fetching
            self._leaver_laptop_info = laptop
            if not self._leaver_laptop_frame:
                return
            try:
                if not self._leaver_laptop_frame.winfo_exists():
                    return
            except tk.TclError:
                return
            if laptop:
                self._draw_laptop_card_found(laptop)
            else:
                self._draw_laptop_card_not_found()

        self.after(0, _update)

    @staticmethod
    def _build_laptop_comment_template(laptop: dict) -> str:
        return (
            "Hello, please calculate residual value of laptop,\n\n"
            f"Model: {laptop['model']}\n"
            f"SN: {laptop['serial']}"
        )

    def _fill_laptop_comment_template(self, laptop: dict):
        """Pre-fill the comment text box with the laptop buyout template."""
        if not self._leaver_comment_box:
            return
        template = self._build_laptop_comment_template(laptop)
        self._leaver_comment_box.delete("1.0", "end")
        self._leaver_comment_box.insert("1.0", template)
        self._leaver_detail_canvas.yview_moveto(0.7)  # scroll down to comment area

    def _post_current_laptop_template(self):
        if self._leaver_sel is None or self._leaver_sel >= len(self.leaver_tickets):
            return
        if not self._leaver_laptop_info:
            messagebox.showinfo(
                "Laptop not ready",
                "Laptop details are not available yet. Wait for Snipe-IT to load or check whether a laptop was found.",
                parent=self,
            )
            return

        ticket = self.leaver_tickets[self._leaver_sel]
        template = self._build_laptop_comment_template(self._leaver_laptop_info)
        if self._leaver_comment_box:
            self._leaver_comment_box.delete("1.0", "end")
            self._leaver_comment_box.insert("1.0", template)
        self._leaver_post_comment_text(
            ticket["id"],
            ticket["key"],
            template,
            success_text="Buyout template posted!",
        )

    # ── Add accountants automation ────────────────────────────────────────────

    _ACCOUNTANTS_RULE_NAME = "Add accountants for deduction | LT Group 1"

    def _leaver_add_accountants(self):
        if self._leaver_sel is None or self._leaver_sel >= len(self.leaver_tickets):
            return
        t = self.leaver_tickets[self._leaver_sel]
        if not messagebox.askyesno(
            "Add accountants",
            f"Trigger automation on {t['key']}?\n\n"
            f'"{self._ACCOUNTANTS_RULE_NAME}"\n\n'
            "This only triggers the Jira automation rule. Jira will handle adding accountants as request participants.",
            parent=self,
        ):
            return
        self._leavers_status.set("Triggering automation...")
        self._add_accountants_btn.config(state="disabled")

        def _do():
            try:
                self.jira.trigger_manual_automation(
                    t["key"], t["id"], self._ACCOUNTANTS_RULE_NAME
                )
                self.after(0, lambda: self._leavers_status.set(
                    f"Automation triggered for {t['key']}."))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: (
                    self._leavers_status.set("Automation failed."),
                    messagebox.showerror("Automation failed", err, parent=self),
                ))
            finally:
                self.after(0, lambda: self._add_accountants_btn.config(state="normal"))
        threading.Thread(target=_do, daemon=True).start()

    # ── Leavers comments ──────────────────────────────────────────────────────

    def _leaver_fetch_comments(self, issue_key: str, box: tk.Text):
        try:
            comments = self.jira.get_comments(issue_key)
            self._leaver_comments_cache[issue_key] = comments
            self.after(0, lambda: self._populate_comments(box, comments))
        except Exception as e:
            self.after(0, lambda: self._set_comments_text(box, f"Could not load comments: {e}"))

    def _leaver_post_comment(self, ticket_id: str, issue_key: str):
        if not self._leaver_comment_box:
            return
        text = self._leaver_comment_box.get("1.0", "end-1c").strip()
        if not text:
            return
        self._leaver_post_comment_text(ticket_id, issue_key, text)

    def _leaver_post_comment_text(
        self,
        ticket_id: str,
        issue_key: str,
        text: str,
        success_text: str = "Posted!",
    ):
        self._leaver_post_status.config(text="Posting...", fg=GRAY)
        self.update()

        def _do():
            try:
                self.jira.post_comment(issue_key, text)
                self._leaver_comments_cache.pop(issue_key, None)
                def _ok():
                    self._leaver_post_status.config(text=success_text, fg=GREEN)
                    if self._leaver_comment_box:
                        self._leaver_comment_box.delete("1.0", "end")
                    # Reload comments
                    if (self._leaver_sel is not None
                            and self._leaver_sel < len(self.leaver_tickets)
                            and self.leaver_tickets[self._leaver_sel]["id"] == ticket_id):
                        self._show_leaver_detail(self.leaver_tickets[self._leaver_sel])
                self.after(0, _ok)
            except Exception as e:
                self.after(0, lambda: self._leaver_post_status.config(
                    text=f"Error: {e}", fg=RED))
        threading.Thread(target=_do, daemon=True).start()

    # ── Leavers notes ─────────────────────────────────────────────────────────

    # ── Leavers actions ───────────────────────────────────────────────────────

    def _generate_leaver_return_act(self):
        if self._leaver_sel is None or self._leaver_sel >= len(self.leaver_tickets):
            return
        ticket = self.leaver_tickets[self._leaver_sel]
        if self._leaver_doc_btn:
            self._leaver_doc_btn.config(state="disabled")
        self._leavers_status.set("Generating return act...")

        def _do():
            try:
                asset_warning = None
                if self._snipeit:
                    try:
                        user = self._snipeit.find_user(
                            ticket.get("first_name", ""), ticket.get("last_name", "")
                        )
                        if user:
                            assets = self._snipeit.get_user_assets(user["id"])
                            if not assets:
                                asset_warning = (
                                    f"Snipe-IT found the user but no assets are assigned to "
                                    f"{ticket.get('name', 'this person')}.\n\n"
                                    "The asset table in the return act will be empty.\n\n"
                                    "Generate anyway?"
                                )
                        else:
                            asset_warning = (
                                f"Snipe-IT could not find a user matching "
                                f"{ticket.get('name', 'this person')}.\n\n"
                                "The asset table in the return act will be empty.\n\n"
                                "Generate anyway?"
                            )
                    except Exception as exc:
                        asset_warning = (
                            f"Snipe-IT lookup failed: {exc}\n\n"
                            "The asset table in the return act will be empty.\n\n"
                            "Generate anyway?"
                        )

                if asset_warning:
                    proceed = threading.Event()
                    confirmed = [False]

                    def _ask():
                        confirmed[0] = messagebox.askyesno(
                            "No assets found", asset_warning, parent=self
                        )
                        proceed.set()

                    self.after(0, _ask)
                    proceed.wait()

                    if not confirmed[0]:
                        self.after(0, lambda: self._leavers_status.set("Return act cancelled."))
                        return

                path, warnings = generate_leaver_return_document(ticket, self._snipeit)

                def _ok():
                    self._leavers_status.set(f"Return act generated for {ticket['key']}.")
                    if hasattr(os, "startfile"):
                        os.startfile(path)
                    if warnings:
                        messagebox.showwarning(
                            "Return act generated",
                            "The document was created, but some fields could not be filled automatically:\n\n"
                            + "\n".join(f"- {warning}" for warning in warnings),
                            parent=self,
                        )

                self.after(0, _ok)
            except Exception as e:
                self.after(0, lambda: (
                    self._leavers_status.set("Return act generation failed."),
                    messagebox.showerror("Return act generation failed", str(e), parent=self),
                ))
            finally:
                if self._leaver_doc_btn:
                    self.after(0, lambda: self._leaver_doc_btn.config(state="normal"))
        threading.Thread(target=_do, daemon=True).start()

    def _leaver_open_jira(self):
        if self._leaver_sel is not None and self._leaver_sel < len(self.leaver_tickets):
            webbrowser.open(self.leaver_tickets[self._leaver_sel]["url"])

    def _update_leaver_open_btn(self):
        has_sel = (self._leaver_sel is not None
                   and self._leaver_sel < len(self.leaver_tickets))
        if self._leaver_open_btn:
            if has_sel:
                self._leaver_open_btn.config(state="normal", bg=ACCENT, fg=WHITE)
            else:
                self._leaver_open_btn.config(state="disabled", bg="#DDE3EA", fg=GRAY)
        if self._leaver_doc_btn:
            if has_sel:
                self._leaver_doc_btn.config(state="normal", bg=GREEN, fg=WHITE)
            else:
                self._leaver_doc_btn.config(state="disabled", bg="#DDE3EA", fg=GRAY)
        if self._add_accountants_btn:
            if has_sel:
                self._add_accountants_btn.config(state="normal", bg="#FF991F", fg=WHITE)
            else:
                self._add_accountants_btn.config(state="disabled", bg="#DDE3EA", fg=GRAY)

    def update_leaver_tickets(self, tickets: list):
        self.leaver_tickets = tickets
        self._refresh_leavers_list()
        self._leavers_status.set(f"Loaded {len(self.leaver_tickets)} leaver ticket(s).")
        if self._leaver_sel is not None and self._leaver_sel < len(self.leaver_tickets):
            self._show_leaver_detail(self.leaver_tickets[self._leaver_sel])
        else:
            self._leaver_sel = None
            if self._leaver_hint:
                self._leaver_hint.place(relx=0.5, rely=0.5, anchor="center")
            if self._leaver_detail_canvas:
                self._leaver_detail_canvas.place_forget()
            if self._leaver_detail_sb:
                self._leaver_detail_sb.place_forget()
        self._update_leaver_open_btn()

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
            company_tag = self._company_title_suffix(t) if self._is_priority_company(t) else ""
            label = f"  {t['key']}  {t['name']}{company_tag}  [{done}/{len(TASKS)}]  {date_tag}{ad_tag}"
            self._listbox.insert("end", label)
            if self._is_priority_company(t):
                color = PRIORITY_COMPANY_COLOR
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

    def _joiner_type(self, ticket: dict) -> str:
        """Return new_joiner/rejoiner/checking for the header badge."""
        if ticket.get("rejoiner", "").strip().casefold() == "yes":
            return "rejoiner"
        setup_scenario = self.storage.get_ad_setup(ticket.get("id", "")).get("scenario", "")
        if setup_scenario == "new_joiner":
            return "new_joiner"
        if setup_scenario in ("rejoiner_dual", "rejoiner_single"):
            return "rejoiner"
        scenario = ticket.get("ad_joiner_scenario", "")
        if scenario in ("rejoiner_dual", "rejoiner_single"):
            return "rejoiner"
        if scenario == "checking":
            return "checking"
        return "new_joiner"

    def _ensure_ad_joiner_type_check(self, ticket: dict):
        """Use AD as the source of truth when Jira says the person is not a rejoiner."""
        ticket_id = ticket.get("id", "")
        if not ticket_id:
            return
        if ticket.get("rejoiner", "").strip().casefold() == "yes":
            return
        setup_scenario = self.storage.get_ad_setup(ticket_id).get("scenario", "")
        if setup_scenario:
            ticket["ad_joiner_scenario"] = setup_scenario
            return
        if ticket.get("ad_joiner_scenario"):
            return
        first = ticket.get("first_name", "")
        last = ticket.get("last_name", "")
        if not first or not last:
            return
        if ticket_id in self._ad_joiner_checks:
            return

        self._ad_joiner_checks.add(ticket_id)
        ticket["ad_joiner_scenario"] = "checking"

        def _do():
            try:
                accounts = find_user_accounts(first, last)
                scenario = classify_scenario(accounts)
            except Exception:
                scenario = "ad_check_failed"

            def _apply():
                self._ad_joiner_checks.discard(ticket_id)
                for current in self.tickets:
                    if current.get("id") == ticket_id:
                        current["ad_joiner_scenario"] = scenario
                        break
                self._refresh_list()
                if (self._sel is not None and self._sel < len(self.tickets)
                        and self.tickets[self._sel].get("id") == ticket_id):
                    self._show_detail(self.tickets[self._sel])

            self.after(0, _apply)

        threading.Thread(target=_do, daemon=True).start()

    # ── Detail / task panel ───────────────────────────────────────────────────

    @staticmethod
    def _is_priority_company(ticket: dict) -> bool:
        return "willgrow" in (ticket.get("company_name") or "").casefold()

    @staticmethod
    def _company_title_suffix(ticket: dict) -> str:
        company = (ticket.get("company_name") or "").strip()
        return f"  -  {company}" if company else ""

    def _show_detail(self, t: dict):
        self._save_current_notes()
        self._sync_ad_task(t["id"])
        self._ensure_ad_joiner_type_check(t)
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
        joiner_type = self._joiner_type(t)
        is_rejoiner = joiner_type == "rejoiner"
        name_row = tk.Frame(self._detail, bg=BG)
        name_row.pack(anchor="w", padx=24, pady=(20, 2))
        title_color = PRIORITY_COMPANY_COLOR if self._is_priority_company(t) else TEXT
        tk.Label(name_row, text=f"{t['name']}{self._company_title_suffix(t)}", bg=BG, fg=title_color,
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        if joiner_type == "checking":
            badge_text = "Checking AD..."
            badge_bg = SOFT_BLUE
            badge_fg = ACCENT
        else:
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

        notes_box = self._make_text_box(self._detail, height=5)
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
        self._bind_text_widget_scroll(notes_box, self._detail_canvas)

        # Comments
        tk.Frame(self._detail, bg=BORDER, height=1).pack(fill="x", padx=24, pady=(14, 8))
        tk.Label(self._detail, text="Jira comments", bg=BG, fg=GRAY,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 4))

        comments_frame = tk.Frame(self._detail, bg=BG)
        comments_frame.pack(fill="x", padx=24, pady=(0, 16))
        comments_frame.columnconfigure(0, weight=1)

        comments_box = self._make_text_box(comments_frame, height=12, readonly=True,
                                           font=("Segoe UI", 9))
        comments_sb = tk.Scrollbar(comments_frame, orient="vertical",
                                   command=comments_box.yview)
        comments_box.configure(yscrollcommand=comments_sb.set)
        comments_box.grid(row=0, column=0, sticky="ew")
        comments_sb.grid(row=0, column=1, sticky="ns")
        self._bind_text_widget_scroll(comments_box, self._detail_canvas)

        if t["key"] in self._comments_cache:
            cached_comments = self._comments_cache[t["key"]]
            self._populate_comments(comments_box, cached_comments)
            if t["id"] not in self._buddy_fetched:
                # Buddy resolution involves PowerShell AD calls — always off-thread.
                threading.Thread(
                    target=self._resolve_and_show_buddy,
                    args=(t["id"], cached_comments),
                    daemon=True,
                ).start()
        else:
            self._set_comments_text(comments_box, "Loading...")

        # Always refresh comments in the background so new Jira replies show up
        # even when the app has been running with a stale in-memory cache.
        threading.Thread(
            target=self._fetch_comments,
            args=(t["key"], t["id"], comments_box),
            daemon=True,
        ).start()

        self._bind_detail_scroll(self._detail)
        done = self.storage.completed_count(t["id"], len(TASKS))
        self._status.set(f"  {done}/{len(TASKS)} tasks completed")
        self._update_ad_button()
        self._update_ask_btn()

    def _bind_detail_scroll(self, widget):
        """Recursively bind mousewheel on all detail children to scroll the outer canvas."""
        widget.bind("<MouseWheel>",
            lambda e: self._scroll_canvas_from_event(self._detail_canvas, e))
        for child in widget.winfo_children():
            if isinstance(child, tk.Text):
                continue
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

    def _sync_persisted_buddy_state(self):
        # Tickets are often loaded after the window has already been created,
        # so resync stored manual/dismissed buddy state whenever the live list changes.
        self._load_manual_buddies()
        self._load_dismissed_buddies()

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
            tk.Label(frame, text="Scanning comments for buddy info...",
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
        source = self._buddy_source_text(buddy)
        tk.Label(frame, text=source, bg=SOFT_BLUE, fg=GRAY,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(2, 8))

    @staticmethod
    def _buddy_caption(buddy: dict) -> str:
        display_name = buddy.get("display_name", "")
        sam = buddy.get("name", "")
        if display_name and display_name.lower() != sam.lower():
            return f"{display_name} ({sam})"
        return sam or display_name

    @staticmethod
    def _buddy_source_text(buddy: dict) -> str:
        if buddy.get("author") == "manual":
            return "Set manually"
        if buddy.get("source") == "similar_role_field":
            return "From Jira field: Person who is working in the similar job role"
        return f"From comment by {buddy.get('author', '')}  •  {buddy.get('date', '')}"

    def _fill_multiple_buddy_box(self, frame: tk.Frame, buddy: dict, ticket_id: str):
        frame.configure(bg="#FFF4E5", highlightbackground="#FF991F", highlightthickness=1)

        tk.Label(frame, text="Multiple buddies found — choose one",
                 bg="#FFF4E5", fg="#B76E00",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        sources = {
            (candidate.get("author", ""), candidate.get("date", ""))
            for candidate in buddy.get("candidates", [])
        }
        if len(sources) == 1:
            source = f"From comment by {buddy['author']}  •  {buddy['date']}"
        else:
            source = "Detected across multiple Jira comments"
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

            source = self._buddy_source_text(candidate)
            tk.Label(card, text=source, bg=card_bg, fg=GRAY,
                     font=("Segoe UI", 8), wraplength=440, justify="left").pack(
                         anchor="w", padx=8, pady=(0, 4))

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
        source = self._buddy_source_text(buddy)
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

    def _resolve_and_show_buddy(self, ticket_id: str, comments: list[dict]):
        """Resolve buddy from already-cached comments, off the UI thread."""
        buddy = self._resolve_buddy_from_comments(ticket_id, comments)
        self._buddy_hint[ticket_id] = buddy
        self._buddy_fetched.add(ticket_id)
        self.after(0, lambda: self._refresh_buddy_box(ticket_id, buddy))

    def _resolve_buddy_from_comments(self, ticket_id: str, comments: list[dict]) -> dict | None:
        if ticket_id in self._manual_buddies:
            return self._buddy_hint.get(ticket_id)
        ticket_buddy = self._similar_role_buddy_candidate(ticket_id)
        if ticket_buddy:
            resolved = self._resolve_detected_buddies(ticket_id, [ticket_buddy])
            if resolved:
                return resolved
        return self._resolve_detected_buddies(
            ticket_id, extract_buddies_from_comments(comments)
        )

    def _similar_role_buddy_candidate(self, ticket_id: str) -> dict | None:
        for ticket in self.tickets:
            if ticket.get("id") == ticket_id:
                return ticket.get("similar_role_buddy")
        return None

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
        if self.on_leaver_refresh:
            self.on_leaver_refresh()

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
        self._sync_persisted_buddy_state()
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

        if info.get("phone") or info.get("sms_template"):
            handoff = tk.Frame(box, bg="#E7F4EC")
            handoff.pack(fill="x", padx=10, pady=(0, 10))

            if info.get("phone"):
                phone_row = tk.Frame(handoff, bg="#E7F4EC")
                phone_row.pack(fill="x", pady=(0, 6))
                tk.Label(phone_row, text=f"Phone: {info['phone']}", bg="#E7F4EC", fg=TEXT,
                         font=("Segoe UI", 9, "bold")).pack(side="left")
                self._make_btn(
                    phone_row, "Copy phone",
                    lambda phone=info["phone"]: self._copy_to_clipboard(phone),
                    WHITE, GREEN,
                ).pack(side="left", padx=(8, 0))

            if info.get("sms_template"):
                sms_row = tk.Frame(handoff, bg="#E7F4EC")
                sms_row.pack(fill="x")
                tk.Label(sms_row, text="SMS message:", bg="#E7F4EC", fg=GRAY,
                         font=("Segoe UI", 9, "bold")).pack(side="left")
                self._make_btn(
                    sms_row, "Copy message",
                    lambda text=info["sms_template"]: self._copy_to_clipboard(text),
                    WHITE, GREEN,
                ).pack(side="left", padx=(8, 0))

                sms_box = self._make_text_box(handoff, height=5, readonly=False,
                                              font=("Segoe UI", 9))
                sms_box.insert("1.0", info["sms_template"])
                sms_box.config(state="disabled")
                sms_box.pack(fill="x", pady=(4, 0))
                self._bind_text_widget_scroll(sms_box, self._detail_canvas)

    def _update_ad_button(self):
        if not self._ad_btn:
            return
        if self._sel is None or self._sel >= len(self.tickets):
            self._ad_btn.config(state="disabled", text="AD Setup", bg="#DDE3EA", fg=GRAY)
            return
        self._ad_btn.config(state="normal", text="AD Setup", bg="#00875A", fg=WHITE)

    def _ad_setup_completed(self, ticket: dict):
        self.storage.set(ticket["id"], AD_TASK_INDEX, True, len(TASKS))
        setup_scenario = self.storage.get_ad_setup(ticket["id"]).get("scenario", "")
        if setup_scenario:
            ticket["ad_joiner_scenario"] = setup_scenario
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

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text or "")
        self._status.set("Copied to clipboard.")

    @staticmethod
    def _make_btn(parent, text, cmd, fg, bg, width: int | None = None):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                         relief="flat", bd=0, font=("Segoe UI", 9),
                         padx=10, pady=4, cursor="hand2", width=width,
                         activebackground=ACCENT, activeforeground=WHITE)

    @staticmethod
    def _make_text_box(parent, height: int, readonly: bool = False,
                       font=("Segoe UI", 10)) -> tk.Text:
        box = tk.Text(
            parent,
            height=height,
            relief="flat",
            bd=0,
            font=font,
            bg=INPUT_BG,
            fg=TEXT,
            wrap="word",
            padx=8,
            pady=6,
            undo=not readonly,
            insertbackground=TEXT,
            highlightthickness=1,
            highlightbackground=INPUT_BORDER,
            highlightcolor=ACCENT,
        )
        if readonly:
            box.config(state="disabled")
        return box

    @staticmethod
    def _wheel_units(event) -> int:
        delta = getattr(event, "delta", 0)
        if not delta:
            return -1
        units = int(-delta / 120)
        if units:
            return units
        return -1 if delta > 0 else 1

    def _scroll_canvas_from_event(self, canvas: tk.Canvas, event) -> str:
        canvas.yview_scroll(self._wheel_units(event), "units")
        return "break"

    def _bind_text_widget_scroll(self, widget: tk.Text, canvas: tk.Canvas):
        def _on_wheel(event):
            units = self._wheel_units(event)
            first, last = widget.yview()
            at_top = first <= 0.0
            at_bottom = last >= 1.0
            if (units < 0 and at_top) or (units > 0 and at_bottom):
                canvas.yview_scroll(units, "units")
            else:
                widget.yview_scroll(units, "units")
            return "break"

        widget.bind("<MouseWheel>", _on_wheel)


class SetupDialog(tk.Toplevel):
    """First-run / settings configuration dialog. Result in .result dict."""

    DEFAULTS = {
        "jira_url":              "https://girteka.atlassian.net",
        "email":                 "",
        "api_token":             "",
        "jql":                   'assignee = currentUser() AND issuetype = "SF: Employee onboarding" AND status in (Open, "In Progress", Pending)',
        "date_field":            "customfield_10980",
        "leaver_jql":            'assignee = currentUser() AND (labels = leaver OR cf[11032] = "SF:offboarding" OR summary ~ "Leaver" OR summary ~ "offboarding") AND status not in (Done, Closed, Resolved, Declined, Cancelled, Rejected)',
        "snipeit_url":           "https://inventory.girteka.eu",
        "snipeit_token":         "",
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
            ("Jira URL",               "jira_url",               False,
             "https://girteka.atlassian.net"),
            ("Email",                  "email",                  False,
             "Your Atlassian account email"),
            ("API Token",              "api_token",              True,
             "Create at id.atlassian.com -> Security -> API tokens"),
            ("Joiners JQL",            "jql",                    False,
             'Filter for onboarding tickets - issue type is "SF: Employee onboarding"'),
            ("Start date field",       "date_field",             False,
             "customfield_10980  (do not change unless Jira schema changed)"),
            ("Leavers JQL",            "leaver_jql",             False,
             'Filter for leaver tickets - label "leaver" in the ITHW project'),
            ("Snipe-IT URL",           "snipeit_url",            False,
             "https://inventory.girteka.eu"),
            ("Snipe-IT API Token",     "snipeit_token",          True,
             "Personal access token from Snipe-IT → Profile → API"),
            ("Remind N days before",   "remind_days_before",     False,
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
            "leaver_jql":             self._vars["leaver_jql"].get().strip(),
            "snipeit_url":            self._vars["snipeit_url"].get().strip().rstrip("/"),
            "snipeit_token":          self._vars["snipeit_token"].get().strip(),
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
