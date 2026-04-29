"""
SONS of BANE — Audit Tool GUI
Wraps sob_audit.py in a tkinter interface.
Run with: python sob_audit_gui.py
"""

import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from pathlib import Path
from datetime import date
import os
import re

# Attempt to import from sob_audit; if missing deps, show install prompt
try:
    from sob_audit import (
        load_env, SoBClient, collect_corp, run_corp, run_alliance,
        run_character, ReportBuilder, build_alliance_workbook,
        _safe_filename, MONTH_ABBRS, _cache
    )
    DEPS_OK = True
except ImportError as _e:
    DEPS_OK = False
    DEPS_ERR = str(_e)
    _cache = None

ENV_FILE = Path(__file__).parent / "Auth.env"
REPORTS_DIR = Path(__file__).parent / "reports"

# ─── COLOUR PALETTE (matches the sci-fi theme) ────────────────────────────────
BG       = "#0D1117"
BG_MID   = "#161B22"
BG_LIGHT = "#1F2937"
CYAN     = "#00BFFF"
TEAL     = "#00E5CC"
GOLD     = "#FFD700"
RED      = "#C0392B"
GREEN    = "#27AE60"
GREY     = "#8B949E"
WHITE    = "#FFFFFF"
HEADER   = "#0A3D62"


def styled_btn(parent, text, command, color=CYAN, width=20):
    return tk.Button(
        parent, text=text, command=command,
        bg=color, fg=BG, font=("Calibri", 10, "bold"),
        relief="flat", cursor="hand2", width=width,
        activebackground=WHITE, activeforeground=BG,
        padx=8, pady=4
    )


def label(parent, text, color=GREY, size=9, bold=False):
    return tk.Label(
        parent, text=text, bg=BG_MID, fg=color,
        font=("Calibri", size, "bold" if bold else "normal")
    )


def entry(parent, textvariable=None, show=None, width=60):
    return tk.Entry(
        parent, textvariable=textvariable, show=show,
        bg=BG_LIGHT, fg=WHITE, insertbackground=WHITE,
        relief="flat", font=("Calibri", 9),
        width=width, bd=4
    )


class AuditApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("◈  SONS of BANE  ·  ALLIANCE AUDIT TOOL  ◈")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(780, 680)

        self._corps: list[tuple[int, str]] = []
        self._client: SoBClient | None = None
        self._running = False

        self._build_ui()
        self._load_env_to_ui()

        if not DEPS_OK:
            self._install_deps_prompt()

    # ─── UI CONSTRUCTION ──────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Banner ────────────────────────────────────────────────────────────
        banner = tk.Frame(self, bg=BG, pady=6)
        banner.pack(fill="x")
        tk.Label(
            banner,
            text="◈  SONS of BANE  ·  ALLIANCE AUDIT TOOL  ◈",
            bg=BG, fg=CYAN, font=("Calibri", 16, "bold")
        ).pack()
        tk.Label(
            banner,
            text="EVE Online  ·  Fleet Activity & Compliance Reporting",
            bg=BG, fg=GREY, font=("Calibri", 9)
        ).pack()

        sep = tk.Frame(self, bg=HEADER, height=2)
        sep.pack(fill="x", padx=12)

        # ── Main content ──────────────────────────────────────────────────────
        main = tk.Frame(self, bg=BG, padx=14, pady=10)
        main.pack(fill="both", expand=True)

        # ─ Left panel ─────────────────────────────────────────────────────────
        left = tk.Frame(main, bg=BG, width=360)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        self._build_session_panel(left)
        self._build_target_panel(left)
        self._build_options_panel(left)
        self._build_cache_panel(left)

        # ─ Right panel (log) ──────────────────────────────────────────────────
        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_log_panel(right)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Ready.")
        statusbar = tk.Label(
            self, textvariable=self._status_var,
            bg=HEADER, fg=GREY, font=("Calibri", 8),
            anchor="w", padx=8, pady=3
        )
        statusbar.pack(fill="x", side="bottom")

    def _section(self, parent, title):
        """Create a titled section frame."""
        outer = tk.Frame(parent, bg=BG_MID, bd=0, pady=0)
        outer.pack(fill="x", pady=(0, 8))
        hdr = tk.Frame(outer, bg=HEADER, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, bg=HEADER, fg=CYAN,
                 font=("Calibri", 9, "bold"), padx=8).pack(anchor="w")
        body = tk.Frame(outer, bg=BG_MID, padx=10, pady=8)
        body.pack(fill="x")
        return body

    def _build_session_panel(self, parent):
        body = self._section(parent, "SESSION CREDENTIALS")

        label(body, "Session ID  (sessionid= value from Chrome DevTools)").pack(anchor="w")
        self._session_id_var = tk.StringVar()
        entry(body, textvariable=self._session_id_var, show="•", width=46).pack(fill="x", pady=(2, 6))

        label(body, "CSRF Token  (csrftoken= value)").pack(anchor="w")
        self._csrf_var = tk.StringVar()
        entry(body, textvariable=self._csrf_var, show="•", width=46).pack(fill="x", pady=(2, 8))

        btns = tk.Frame(body, bg=BG_MID)
        btns.pack(fill="x")
        styled_btn(btns, "💾  Save Credentials", self._save_env, color=TEAL, width=22).pack(side="left")
        tk.Label(btns, text="  Saved to Auth.env", bg=BG_MID, fg=GREY,
                 font=("Calibri", 8)).pack(side="left", padx=6)

        self._session_status = tk.Label(body, text="", bg=BG_MID,
                                        fg=GREY, font=("Calibri", 8))
        self._session_status.pack(anchor="w", pady=(4, 0))

    def _build_target_panel(self, parent):
        body = self._section(parent, "AUDIT TARGET")

        label(body, "Corporation").pack(anchor="w")
        corp_row = tk.Frame(body, bg=BG_MID)
        corp_row.pack(fill="x", pady=(2, 6))

        self._corp_var = tk.StringVar(value="— click Load Corps —")
        self._corp_combo = ttk.Combobox(
            corp_row, textvariable=self._corp_var,
            state="readonly", font=("Calibri", 9), width=32
        )
        self._corp_combo.pack(side="left", fill="x", expand=True)
        self._style_combobox()

        styled_btn(corp_row, "⟳", self._load_corps, color=HEADER, width=3).pack(side="left", padx=(6, 0))

        label(body, "Year").pack(anchor="w")
        yr_row = tk.Frame(body, bg=BG_MID)
        yr_row.pack(fill="x", pady=(2, 8))
        self._year_var = tk.StringVar(value=str(date.today().year))
        years = [str(y) for y in range(date.today().year, date.today().year - 4, -1)]
        ttk.Combobox(
            yr_row, textvariable=self._year_var,
            values=years, state="readonly",
            font=("Calibri", 9), width=8
        ).pack(side="left")

        # Action buttons
        styled_btn(body, "▶  Run Corp Report", self._run_corp, color=CYAN, width=28).pack(fill="x", pady=(0, 4))
        styled_btn(body, "★  Run ALL SONS of BANE Corps", self._run_alliance, color=GOLD, width=28).pack(fill="x")

    def _build_options_panel(self, parent):
        body = self._section(parent, "OUTPUT")

        label(body, "Reports folder").pack(anchor="w")
        out_row = tk.Frame(body, bg=BG_MID)
        out_row.pack(fill="x", pady=(2, 6))
        self._out_var = tk.StringVar(value=str(REPORTS_DIR))
        entry(out_row, textvariable=self._out_var, width=36).pack(side="left", fill="x", expand=True)
        styled_btn(out_row, "…", self._browse_out, color=BG_LIGHT, width=3).pack(side="left", padx=(4, 0))

        self._open_btn = styled_btn(body, "📂  Open Reports Folder", self._open_reports, color=BG_LIGHT, width=28)
        self._open_btn.pack(fill="x", pady=(4, 0))

    def _build_cache_panel(self, parent):
        body = self._section(parent, "DATA CACHE")

        self._cache_stats_var = tk.StringVar(value="—")
        tk.Label(
            body, textvariable=self._cache_stats_var,
            bg=BG_MID, fg=GREY, font=("Calibri", 8),
            justify="left", anchor="w"
        ).pack(fill="x", pady=(0, 6))

        btns = tk.Frame(body, bg=BG_MID)
        btns.pack(fill="x")
        styled_btn(btns, "↻  Refresh Stats", self._refresh_cache_stats,
                   color=BG_LIGHT, width=16).pack(side="left")
        styled_btn(btns, "🗑  Clear Cache", self._clear_cache,
                   color=RED, width=14).pack(side="left", padx=(6, 0))

        self._refresh_cache_stats()

    def _refresh_cache_stats(self):
        if not DEPS_OK or _cache is None:
            self._cache_stats_var.set("Cache unavailable (deps missing)")
            return
        s = _cache.stats()
        if s["count"] == 0:
            self._cache_stats_var.set("Cache empty")
        else:
            self._cache_stats_var.set(
                f"{s['count']} entries  ·  {s['size_kb']} KB\n"
                f"Oldest: {s['oldest']}  ·  Newest: {s['newest']}"
            )

    def _clear_cache(self):
        if not DEPS_OK or _cache is None:
            return
        n = _cache.clear()
        self._log_write(f"[🗑] Cache cleared — {n} entries removed.", "gold")
        self._refresh_cache_stats()

    def _build_log_panel(self, parent):
        hdr = tk.Frame(parent, bg=HEADER, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text="OUTPUT LOG", bg=HEADER, fg=CYAN,
                 font=("Calibri", 9, "bold"), padx=8).pack(side="left")
        styled_btn(hdr, "Clear", self._clear_log, color=BG_LIGHT, width=6).pack(side="right", padx=8)

        self._log = scrolledtext.ScrolledText(
            parent, bg=BG, fg=WHITE, insertbackground=WHITE,
            font=("Consolas", 9), relief="flat", state="disabled",
            wrap="word", bd=0
        )
        self._log.pack(fill="both", expand=True)
        # Tag colours
        self._log.tag_config("cyan",  foreground=CYAN)
        self._log.tag_config("teal",  foreground=TEAL)
        self._log.tag_config("gold",  foreground=GOLD)
        self._log.tag_config("red",   foreground=RED)
        self._log.tag_config("green", foreground=GREEN)
        self._log.tag_config("grey",  foreground=GREY)
        self._log.tag_config("white", foreground=WHITE)

    # ─── STYLE HELPERS ────────────────────────────────────────────────────────
    def _style_combobox(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
                         fieldbackground=BG_LIGHT, background=HEADER,
                         foreground=WHITE, selectbackground=HEADER,
                         selectforeground=WHITE, arrowcolor=CYAN)
        style.map("TCombobox", fieldbackground=[("readonly", BG_LIGHT)])

    # ─── LOG HELPERS ──────────────────────────────────────────────────────────
    def _log_write(self, text: str, tag: str = "white"):
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _status(self, msg: str):
        self._status_var.set(msg)
        self.update_idletasks()

    # ─── ENV HANDLING ─────────────────────────────────────────────────────────
    def _load_env_to_ui(self):
        if not ENV_FILE.exists():
            return
        try:
            env = load_env(ENV_FILE) if DEPS_OK else self._parse_env_raw()
            cookie = env.get("SESSION_COOKIE", "")
            if cookie:
                sid = re.search(r"sessionid=([^;\s]+)", cookie)
                csrf = re.search(r"csrftoken=([^;\s]+)", cookie)
                if sid:
                    self._session_id_var.set(sid.group(1))
                if csrf:
                    self._csrf_var.set(csrf.group(1))
            else:
                self._session_id_var.set(env.get("SESSIONID", ""))
                self._csrf_var.set(env.get("CSRFTOKEN", ""))
            self._session_status.config(text=f"✓ Loaded from {ENV_FILE.name}", fg=GREEN)
        except Exception as e:
            self._session_status.config(text=f"! Could not load env: {e}", fg=RED)

    def _parse_env_raw(self) -> dict:
        data = {}
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
        return data

    def _save_env(self):
        sid = self._session_id_var.get().strip()
        csrf = self._csrf_var.get().strip()
        if not sid or not csrf:
            messagebox.showwarning("Missing Values", "Please enter both Session ID and CSRF Token.")
            return
        cookie = f"sessionid={sid}; csrftoken={csrf}"
        ENV_FILE.write_text(
            f'# Auto-saved by sob_audit_gui.py on {date.today()}\n'
            f'SESSION_COOKIE="{cookie}"\n'
        )
        self._session_status.config(text=f"✓ Saved to {ENV_FILE.name}", fg=GREEN)
        self._log_write(f"[session] Credentials saved to {ENV_FILE.name}", "teal")
        self._client = None  # force re-init on next run

    def _build_client(self) -> SoBClient | None:
        if not DEPS_OK:
            return None
        if not ENV_FILE.exists():
            messagebox.showerror("No Credentials", "Please save your credentials first.")
            return None
        try:
            env = load_env(ENV_FILE)
            return SoBClient(env)
        except Exception as e:
            messagebox.showerror("Auth Error", str(e))
            return None

    # ─── CORP LIST ────────────────────────────────────────────────────────────
    def _load_corps(self):
        if not DEPS_OK:
            messagebox.showerror("Missing Dependencies", DEPS_ERR)
            return
        client = self._build_client()
        if not client:
            return
        self._status("Loading corps from SONS of BANE alliance...")
        self._log_write("[↓] Fetching alliance corp list...", "cyan")

        def worker():
            try:
                today = date.today()
                corps = client.list_alliance_corps(today.year, today.month)
                self._corps = corps
                names = ["★  ALL SONS of BANE CORPS"] + [name for _, name in corps]
                self.after(0, lambda: self._corp_combo.config(values=names))
                self.after(0, lambda: self._corp_var.set(names[1] if len(names) > 1 else ""))
                self.after(0, lambda: self._status(f"Loaded {len(corps)} corps."))
                self.after(0, lambda: self._log_write(
                    f"[✓] Found {len(corps)} corps in SONS of BANE.", "green"))
                for cid, cname in corps:
                    self.after(0, lambda c=cname, i=cid: self._log_write(
                        f"    {c}  ({i})", "grey"))
            except Exception as e:
                self.after(0, lambda: self._log_write(f"[!] Error: {e}", "red"))
                self.after(0, lambda: self._status("Failed to load corps."))

        threading.Thread(target=worker, daemon=True).start()

    # ─── RUN HANDLERS ─────────────────────────────────────────────────────────
    def _get_out_dir(self) -> Path:
        p = Path(self._out_var.get())
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _get_year(self) -> int:
        try:
            return int(self._year_var.get())
        except ValueError:
            return date.today().year

    def _run_corp(self):
        if self._running:
            return
        selected = self._corp_var.get()
        if not selected or "Load Corps" in selected:
            messagebox.showwarning("No Corp Selected", "Please load corps and select one first.")
            return
        if "ALL SONS" in selected:
            self._run_alliance()
            return
        client = self._build_client()
        if not client:
            return

        year = self._get_year()
        out_dir = self._get_out_dir()

        # Match selected name to corp_id
        corp_id = None
        corp_name = selected
        for cid, cname in self._corps:
            if cname == selected:
                corp_id = cid
                break

        self._set_running(True)
        self._log_write(f"\n{'─'*50}", "grey")
        self._log_write(f"[▶] Corp audit: {corp_name}  ({year})", "cyan")
        self._status(f"Running audit for {corp_name}...")

        def gui_log(msg, tag="white"):
            self.after(0, lambda m=msg, t=tag: self._log_write(m, t))

        def worker():
            try:
                if corp_id:
                    corp = collect_corp(client, corp_id, corp_name, year, log_fn=gui_log)
                    rb = ReportBuilder(
                        title=corp_name.upper(),
                        subtitle=(f"Sons of Bane Alliance  ·  EVE Online  ·  "
                                  f"Audit Date: {date.today()}  ·  {len(corp.members)} Mains"),
                        members=corp.members,
                        year=year,
                    )
                    wb = rb.build()
                    out_path = out_dir / f"sob_corp_{_safe_filename(corp_name)}_{date.today()}.xlsx"
                    wb.save(out_path)
                else:
                    out_path = run_corp(client, corp_name, year, out_dir)

                self.after(0, lambda: self._log_write(
                    f"[✓] Report saved: {out_path.name}", "green"))
                self.after(0, lambda: self._status(f"Done → {out_path.name}"))
                self.after(0, lambda: self._prompt_open(out_path))
                self.after(0, self._refresh_cache_stats)
            except Exception as e:
                self.after(0, lambda: self._log_write(f"[!] {e}", "red"))
                self.after(0, lambda: self._status("Audit failed — see log."))
            finally:
                self.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    def _run_alliance(self):
        if self._running:
            return
        if not self._corps:
            messagebox.showwarning("No Corps Loaded", "Click ⟳ to load corps first.")
            return
        client = self._build_client()
        if not client:
            return

        year = self._get_year()
        out_dir = self._get_out_dir()
        self._set_running(True)

        self._log_write(f"\n{'─'*50}", "grey")
        self._log_write(f"[★] Alliance-wide audit: {len(self._corps)} corps  ({year})", "gold")
        self._log_write("    Output: one workbook with Alliance Summary + one sheet per corp", "grey")
        self._status("Running alliance audit...")

        def gui_log(msg, tag="white"):
            self.after(0, lambda m=msg, t=tag: self._log_write(m, t))

        def worker():
            corps_data = []
            for corp_id, corp_name in self._corps:
                try:
                    corp = collect_corp(client, corp_id, corp_name, year, log_fn=gui_log)
                    corps_data.append(corp)
                    self.after(0, lambda n=corp_name, m=len(corp.members): self._log_write(
                        f"      ✓ {n}  ({m} mains)", "green"))
                except Exception as e:
                    self.after(0, lambda n=corp_name, err=e: self._log_write(
                        f"      ! {n}: {err}", "red"))

            try:
                self.after(0, lambda: self._log_write("[…] Building workbook…", "grey"))
                wb = build_alliance_workbook(corps_data, year)
                combined = out_dir / f"sob_alliance_{date.today()}.xlsx"
                wb.save(combined)
                total_mains = sum(len(c.members) for c in corps_data)
                self.after(0, lambda: self._log_write(
                    f"\n[★] Saved: {combined.name}  "
                    f"({len(corps_data)} corps, {total_mains} mains, "
                    f"{len(corps_data) + 1} sheets)", "gold"))
                self.after(0, lambda: self._status(f"Alliance audit done → {combined.name}"))
                self.after(0, lambda: self._prompt_open(combined))
                self.after(0, self._refresh_cache_stats)
            except Exception as e:
                self.after(0, lambda: self._log_write(f"[!] Workbook error: {e}", "red"))
            finally:
                self.after(0, lambda: self._set_running(False))

        threading.Thread(target=worker, daemon=True).start()

    # ─── HELPERS ──────────────────────────────────────────────────────────────
    def _set_running(self, state: bool):
        self._running = state
        cursor = "watch" if state else ""
        self.configure(cursor=cursor)
        if state:
            self._log_write("[…] Working — see progress above as pages load…", "grey")

    def _prompt_open(self, path: Path):
        if messagebox.askyesno("Report Ready",
                               f"Report saved:\n{path.name}\n\nOpen it now?"):
            os.startfile(path)  # Windows; opens with default xlsx viewer

    def _browse_out(self):
        d = filedialog.askdirectory(initialdir=self._out_var.get())
        if d:
            self._out_var.set(d)

    def _open_reports(self):
        p = Path(self._out_var.get())
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(p)

    def _install_deps_prompt(self):
        self._log_write("⚠  Missing Python dependencies.", "gold")
        self._log_write(f"   Error: {DEPS_ERR}", "red")
        self._log_write("   Click 'Install Dependencies' to fix this automatically.", "grey")

        def install():
            self._log_write("[↓] Installing: requests beautifulsoup4 openpyxl lxml…", "cyan")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "requests", "beautifulsoup4", "openpyxl", "lxml"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                self._log_write("[✓] Done! Please restart the app.", "green")
            else:
                self._log_write(f"[!] pip failed:\n{result.stderr}", "red")

        styled_btn(
            self._log.master, "📦  Install Dependencies",
            install, color=GOLD, width=24
        ).pack(pady=6)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = AuditApp()
    # Center window on screen
    app.update_idletasks()
    w, h = 900, 720
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    app.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")
    app.mainloop()
