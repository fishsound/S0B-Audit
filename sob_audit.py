"""
SONS of BANE — Alliance Auth Compliance Audit Tool
===================================================
Parameterized report generator for auth.sonsofbane.com

Replaces the hardcoded mineski_audit.py. Scrapes live data from:
  - Alliance Auth Member Audit plugin  (aa-memberaudit)
  - AFAT Fleet Activity Tracking       (aa-afat)

Usage:
    # Single character by name
    python sob_audit.py character "aduron"

    # Single corp by name or ID
    python sob_audit.py corp "Mineski Infinity"
    python sob_audit.py corp 98614919

    # All 24 SONS of BANE corps
    python sob_audit.py alliance

    # Options
    python sob_audit.py corp "Mineski Infinity" --year 2026 --out ./reports/

Authentication:
    Copy .env.example to .env and paste your browser session cookie.
    See .env.example for details.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Run: pip install requests beautifulsoup4 openpyxl lxml --break-system-packages")
    sys.exit(1)

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.utils import get_column_letter


# ─── CONFIG ───────────────────────────────────────────────────────────────────
BASE_URL = "https://auth.sonsofbane.com"
ESI_BASE  = "https://esi.evetech.net"
SOB_ALLIANCE_ID = 99001969
USER_AGENT = "SoB-Audit-Tool/1.0 (compliance audit; contact: alliance leadership)"
REQUEST_DELAY = 0.05   # per-worker delay — reduced because workers run concurrently
AUTH_WORKERS  = 5      # concurrent requests to auth.sonsofbane.com
ESI_WORKERS   = 10     # concurrent requests to ESI (public, higher tolerance)

# Cache TTLs
TTL_OVERVIEW  = timedelta(hours=24)   # character overview pages
TTL_ESI       = timedelta(hours=24)   # ESI corp/alliance history
TTL_FAT_MONTH = timedelta(hours=2)    # AFAT monthly data (FATs can be logged anytime)
TTL_FINDER    = timedelta(hours=6)    # character finder (membership changes)


# ─── DISK CACHE ───────────────────────────────────────────────────────────────
class Cache:
    """
    Simple JSON-on-disk cache with per-entry TTL.
    Stored in <script_dir>/.cache/  as md5-keyed .json files.
    Thread-safe for reads; writes are atomic via rename.
    """

    def __init__(self, cache_dir: Path | None = None):
        self.dir = (cache_dir or Path(__file__).parent / ".cache")
        self.dir.mkdir(exist_ok=True)

    def _path(self, key: str) -> Path:
        h = hashlib.md5(key.encode()).hexdigest()
        return self.dir / f"{h}.json"

    def get(self, key: str, ttl: timedelta) -> Any:
        """Return cached value or None if missing/expired."""
        p = self._path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            saved_at = datetime.fromisoformat(data["saved_at"])
            if datetime.now() - saved_at > ttl:
                return None
            return data["value"]
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        """Atomically write value to cache."""
        p = self._path(key)
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps({"saved_at": datetime.now().isoformat(), "value": value},
                           default=str),
                encoding="utf-8"
            )
            tmp.replace(p)
        except Exception:
            pass

    def clear(self) -> int:
        """Delete all cache files. Returns count deleted."""
        count = 0
        for f in self.dir.glob("*.json"):
            try:
                f.unlink()
                count += 1
            except Exception:
                pass
        return count

    def stats(self) -> dict:
        """Return {count, size_kb, oldest, newest}."""
        files = list(self.dir.glob("*.json"))
        if not files:
            return {"count": 0, "size_kb": 0, "oldest": None, "newest": None}
        mtimes = [f.stat().st_mtime for f in files]
        return {
            "count": len(files),
            "size_kb": round(sum(f.stat().st_size for f in files) / 1024, 1),
            "oldest": datetime.fromtimestamp(min(mtimes)).strftime("%Y-%m-%d %H:%M"),
            "newest": datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M"),
        }


# Module-level cache instance (shared across all calls in a process)
_cache = Cache()


# ─── COLOUR PALETTE (exact match to mineski_audit.py) ─────────────────────────
C_BG_DARK   = "0D1117"
C_BG_MID    = "161B22"
C_BG_LIGHT  = "1F2937"
C_CYAN      = "00BFFF"
C_TEAL      = "00E5CC"
C_GOLD      = "FFD700"
C_RED_DARK  = "C0392B"
C_GREEN     = "27AE60"
C_GREY_TEXT = "8B949E"
C_WHITE     = "FFFFFF"
C_ORANGE    = "F39C12"
C_HEADER_BG = "0A3D62"

THIN = Side(style="thin", color="2D3748")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)


def font(color=C_WHITE, size=10, bold=False, italic=False):
    return Font(name="Calibri", color=color, size=size, bold=bold, italic=italic)


def align(h="left", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


# ─── DATA MODELS ──────────────────────────────────────────────────────────────
@dataclass
class Character:
    pk: int                       # Member Audit database pk
    name: str
    eve_id: Optional[int] = None
    corp_name: str = ""
    corp_id: Optional[int] = None
    alliance_name: str = ""
    main_name: str = ""
    is_main: bool = False
    # Overview card fields (from /member-audit/character_viewer/<pk>/)
    join_date: str = ""           # not always available — may be derived
    time_in_corp: str = ""
    born: str = ""
    skillpoints_m: float = 0.0
    last_login: str = ""
    sec_status: float = 0.0
    wallet_b: float = 0.0
    assets_b: float = 0.0
    location: str = ""
    ship: str = ""
    # FAT counters
    total_fats: int = 0
    fats_by_year: dict = field(default_factory=dict)        # {2024: n, 2025: n, 2026: n}
    fats_by_month: dict = field(default_factory=dict)       # {"2026-01": n, ...}


@dataclass
class Corp:
    corp_id: int
    name: str
    members: list = field(default_factory=list)   # list[Character] (mains only)


# ─── ENV / COOKIE LOADING ─────────────────────────────────────────────────────
def load_env(env_path: Path = None) -> dict:
    """Parse .env file into dict. Format: KEY=value per line."""
    env_path = env_path or Path(__file__).parent / ".env"
    if not env_path.exists():
        print(f"ERROR: {env_path} not found. Copy .env.example → .env and paste your session cookie.")
        sys.exit(1)
    data = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


# ─── HTTP CLIENT ──────────────────────────────────────────────────────────────
class SoBClient:
    """Authenticated scraper for auth.sonsofbane.com"""

    def __init__(self, env: dict):
        self.base = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        })
        # Cookie can be supplied one of two ways:
        # 1) SESSION_COOKIE="sessionid=abc; csrftoken=def"  (full cookie header)
        # 2) SESSIONID=abc + CSRFTOKEN=def                  (individual values)
        if "SESSION_COOKIE" in env and env["SESSION_COOKIE"]:
            self.session.headers["Cookie"] = env["SESSION_COOKIE"]
            # Parse csrftoken from full cookie string for POST safety
            m = re.search(r"csrftoken=([^;\s]+)", env["SESSION_COOKIE"])
            if m:
                self.session.headers["X-CSRFToken"] = m.group(1)
        else:
            if "SESSIONID" in env:
                self.session.cookies.set("sessionid", env["SESSIONID"], domain="auth.sonsofbane.com")
            if "CSRFTOKEN" in env:
                self.session.cookies.set("csrftoken", env["CSRFTOKEN"], domain="auth.sonsofbane.com")
                self.session.headers["X-CSRFToken"] = env["CSRFTOKEN"]

    def _get(self, path: str, **kwargs):
        url = urljoin(self.base + "/", path.lstrip("/"))
        time.sleep(REQUEST_DELAY)
        r = self.session.get(url, timeout=30, **kwargs)
        if r.status_code == 302 or "login" in r.url.lower():
            raise RuntimeError(
                f"Auth failed (redirected to login). Your session cookie has expired. "
                f"Re-copy it from Chrome DevTools → Application → Cookies → auth.sonsofbane.com"
            )
        r.raise_for_status()
        return r

    # ── Member Audit ──────────────────────────────────────────────────────────
    #
    # character_finder_data returns a 13-column array per row:
    #   [0]  character cell HTML  — <img>+<a href="/member-audit/character_viewer/{pk}/">{name}</a>
    #   [1]  character org HTML   — "{corp}<br><em>{alliance}</em>"
    #   [2]  main cell HTML       — <img>+<a href="/member-audit/character_viewer/{main_pk}/">{main_name}</a>
    #   [3]  main org HTML        — "{corp}<br><em>{alliance}</em>"
    #   [4]  main state text      — e.g. "S0B Member"
    #   [5]  action link HTML     — "View" button
    #   [6]  char alliance (plain)
    #   [7]  char corp (plain)       ← filter on this
    #   [8]  main alliance (plain)
    #   [9]  main corp (plain)
    #   [10] is_main flag         — "yes" / "no"
    #   [11] compliance flag      — "yes" / "no"
    #   [12] eve character ID     — int
    #
    # Server caps length at 100 rows, so we must paginate.
    FINDER_PAGE_SIZE = 100

    def character_finder(self, corp_name: str = "") -> list[list]:
        """Paginate through character_finder_data and return raw row arrays."""
        cache_key = f"finder:{corp_name}"
        cached = _cache.get(cache_key, TTL_FINDER)
        if cached is not None:
            return cached

        all_rows = []
        start = 0
        while True:
            params = {
                "draw": "1",
                "start": str(start),
                "length": str(self.FINDER_PAGE_SIZE),
            }
            # DataTables column definitions so per-column search works
            for i in range(13):
                params[f"columns[{i}][data]"] = str(i)
                params[f"columns[{i}][searchable]"] = "true"
                params[f"columns[{i}][orderable]"] = "false"
                params[f"columns[{i}][search][value]"] = ""
                params[f"columns[{i}][search][regex]"] = "false"
            if corp_name:
                params["columns[7][search][value]"] = corp_name
            r = self._get("/member-audit/character_finder_data", params=params)
            try:
                data = r.json()
            except Exception:
                raise RuntimeError("character_finder_data did not return JSON — are you logged in?")
            rows = data.get("data", [])
            all_rows.extend(rows)
            total = data.get("recordsFiltered", 0)
            start += len(rows)
            if not rows or start >= total:
                break

        _cache.set(cache_key, all_rows)
        return all_rows

    @staticmethod
    def _parse_finder_name_cell(cell_html: str) -> tuple[Optional[int], str]:
        """Extract (pk, name) from column [0] or [2] HTML."""
        soup = BeautifulSoup(cell_html, "lxml")
        a = soup.find("a", href=re.compile(r"/member-audit/character_viewer/\d+/"))
        if not a:
            return None, ""
        m = re.search(r"/character_viewer/(\d+)/", a["href"])
        pk = int(m.group(1)) if m else None
        return pk, a.get_text(strip=True)

    def list_corp_mains(self, corp_name: str) -> list[Character]:
        """Return Character objects (name + pk + eve_id) for all mains in a corp."""
        rows = self.character_finder(corp_name=corp_name)
        mains = []
        for r in rows:
            if len(r) < 13 or r[10] != "yes":
                continue
            pk, name = self._parse_finder_name_cell(r[0])
            if not pk:
                continue
            ch = Character(pk=pk, name=name, is_main=True)
            ch.corp_name = _strip_html(r[7])
            ch.alliance_name = _strip_html(r[6])
            try:
                ch.eve_id = int(r[12])
            except (ValueError, TypeError):
                pass
            mains.append(ch)
        return mains

    def character_overview(self, pk: int) -> dict:
        """Parse the Overview card from /member-audit/character_viewer/<pk>/"""
        cache_key = f"overview:{pk}"
        cached = _cache.get(cache_key, TTL_OVERVIEW)
        if cached is not None:
            return cached

        r = self._get(f"/member-audit/character_viewer/{pk}/")
        soup = BeautifulSoup(r.text, "lxml")
        result = {}
        for dl in soup.select("dl.dl-horizontal"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt, dd in zip(dts, dds):
                key = dt.get_text(strip=True).rstrip(":").strip()
                val = dd.get_text(" ", strip=True)
                if key:
                    result[key] = val
        h1 = soup.find(["h1", "h2"])
        if h1 and "Character" not in result:
            result["Character"] = h1.get_text(strip=True)

        _cache.set(cache_key, result)
        return result

    # ── AFAT (Fleet Activity Tracking) ────────────────────────────────────────
    def corp_fat_month(self, corp_id: int, year: int, month: int) -> dict[str, int]:
        """
        Parse per-main FAT counts for one month from:
          /fleet-activity-tracking/statistics/corporation/{id}/{year}/{month}/
        Only the first table ("Main characters") is used — counts are already
        attributed from alts to mains by the server.
        Current month is never cached (FATs can still be added); all prior months
        are cached with TTL_FAT_MONTH.
        """
        today = date.today()
        is_current = (year == today.year and month == today.month)
        cache_key = f"fat:{corp_id}:{year}:{month}"
        if not is_current:
            cached = _cache.get(cache_key, TTL_FAT_MONTH)
            if cached is not None:
                return cached

        try:
            r = self._get(f"/fleet-activity-tracking/statistics/corporation/{corp_id}/{year}/{month}/")
        except Exception:
            return {}
        soup = BeautifulSoup(r.text, "lxml")
        results = {}
        tables = soup.find_all("table")
        if not tables:
            return results
        main_table = tables[0]  # "Main characters" accumulated FATs
        tbody = main_table.find("tbody")
        if not tbody:
            return results
        for tr in tbody.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) >= 2:
                try:
                    results[cells[0]] = int(cells[1])
                except ValueError:
                    pass

        if not is_current:
            _cache.set(cache_key, results)
        return results

    def list_alliance_corps(self, year: int, month: int) -> list[tuple[int, str]]:
        """
        List all (corp_id, corp_name) in SONS of BANE alliance by scraping the
        AFAT alliance monthly stats page's table. The raw HTML contains all
        rows (DataTables pagination is client-side only).
        """
        cache_key = f"alliance_corps:{year}:{month}"
        cached = _cache.get(cache_key, TTL_FINDER)
        if cached is not None:
            return [(int(r[0]), r[1]) for r in cached]

        r = self._get(f"/fleet-activity-tracking/statistics/alliance/{SOB_ALLIANCE_ID}/{year}/{month}/")
        soup = BeautifulSoup(r.text, "lxml")
        corps = []
        table = soup.find("table")
        if not table or not table.find("tbody"):
            return corps
        for tr in table.find("tbody").find_all("tr"):
            link = tr.find("a", href=re.compile(r"/corporation/(\d+)/"))
            if not link:
                continue
            m = re.search(r"/corporation/(\d+)/", link["href"])
            if not m:
                continue
            corp_id = int(m.group(1))
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            name = cells[0] if cells else f"Corp {corp_id}"
            if (corp_id, name) not in corps:
                corps.append((corp_id, name))

        _cache.set(cache_key, corps)
        return corps


# ─── PARSERS FOR OVERVIEW FIELDS ──────────────────────────────────────────────
def _parse_isk_b(s: str) -> float:
    """'123,456,789.00 ISK' → billions float."""
    if not s:
        return 0.0
    s = s.replace("ISK", "").replace(",", "").strip()
    m = re.search(r"([-+]?\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    return round(float(m.group(1)) / 1e9, 2)


def _parse_sp_m(s: str) -> float:
    """'99,875,432 SP' → millions float."""
    if not s:
        return 0.0
    s = s.replace("SP", "").replace(",", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return 0.0
    return float(m.group(1))


def _parse_sec(s: str) -> float:
    if not s:
        return 0.0
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else 0.0


def _format_duration(start_date: date) -> str:
    """Return human-readable 'X years, Y months' from start_date to today."""
    today = date.today()
    total_days = (today - start_date).days
    years  = total_days // 365
    months = (total_days % 365) // 30
    days   = total_days % 30
    parts = []
    if years:  parts.append(f"{years} year{'s' if years  > 1 else ''}")
    if months: parts.append(f"{months} month{'s' if months > 1 else ''}")
    if not parts:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    return ", ".join(parts[:2])


def get_char_corp_join_date(eve_id: int, corp_id: int) -> Optional[date]:
    """
    Public ESI: when did this character most recently join corp_id?
    Returns a date object, or None on failure.
    """
    cache_key = f"esi_char:{eve_id}:{corp_id}"
    cached = _cache.get(cache_key, TTL_ESI)
    if cached is not None:
        return date.fromisoformat(cached) if cached != "__none__" else None

    result: Optional[date] = None
    try:
        r = requests.get(
            f"{ESI_BASE}/v2/characters/{eve_id}/corporationhistory/",
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        history = r.json()          # ascending by record_id
        for entry in reversed(history):
            if entry.get("corporation_id") == corp_id:
                result = datetime.fromisoformat(
                    entry["start_date"].replace("Z", "+00:00")
                ).date()
                break
    except Exception:
        pass

    _cache.set(cache_key, result.isoformat() if result else "__none__")
    return result


def get_corp_alliance_join_date(corp_id: int) -> Optional[date]:
    """
    Public ESI: when did corp_id most recently join SONS of BANE (alliance 99001969)?
    Returns a date object, or None on failure.
    """
    cache_key = f"esi_corp:{corp_id}"
    cached = _cache.get(cache_key, TTL_ESI)
    if cached is not None:
        return date.fromisoformat(cached) if cached != "__none__" else None

    result: Optional[date] = None
    try:
        r = requests.get(
            f"{ESI_BASE}/v2/corporations/{corp_id}/alliancehistory/",
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        history = r.json()          # ascending by record_id
        for entry in reversed(history):
            if entry.get("alliance_id") == SOB_ALLIANCE_ID:
                result = datetime.fromisoformat(
                    entry["start_date"].replace("Z", "+00:00")
                ).date()
                break
    except Exception:
        pass

    _cache.set(cache_key, result.isoformat() if result else "__none__")
    return result


def compute_alliance_tenure(char_corp_join: Optional[date],
                            corp_alliance_join: Optional[date]) -> tuple[str, str]:
    """
    Return (joined_str, time_in_alliance_str).

    joined_str         = when the character joined their corp (raw corp join date).
    time_in_alliance   = duration since the LATER of:
                           • when the character joined the corp
                           • when the corp joined SONS of BANE
                         This ensures a pilot who was in a corp before it joined
                         the alliance doesn't get credit for pre-alliance tenure.
    """
    if not char_corp_join:
        return "—", "—"
    joined_str = char_corp_join.strftime("%Y-%b-%d")

    # Cap effective start at the corp's alliance join date if it's more recent
    effective_start = char_corp_join
    if corp_alliance_join and corp_alliance_join > char_corp_join:
        effective_start = corp_alliance_join

    return joined_str, _format_duration(effective_start)


def character_from_overview(pk: int, overview: dict) -> Character:
    """Map Overview card dict → Character model."""
    c = Character(pk=pk, name=overview.get("Character") or overview.get("Name") or f"char_{pk}")
    c.corp_name = overview.get("Corporation", "")
    c.alliance_name = overview.get("Alliance", "")
    c.main_name = overview.get("Main", "")
    c.is_main = (c.main_name == c.name or not c.main_name)
    c.born = overview.get("Born", "")
    c.last_login = overview.get("Last Login", "")
    c.location = overview.get("Location", "") or overview.get("System", "")
    c.ship = overview.get("Ship", "")
    # Member Audit uses "Skill Points" (with space); also accept "Skillpoints" / "SP"
    sp_raw = (overview.get("Skill Points")
              or overview.get("Skillpoints")
              or overview.get("Total Skill Points")
              or overview.get("SP")
              or next((v for k, v in overview.items()
                       if "skill" in k.lower() and "point" in k.lower()), ""))
    c.skillpoints_m = _parse_sp_m(sp_raw)
    c.sec_status = _parse_sec(overview.get("Sec. Status", ""))
    c.wallet_b = _parse_isk_b(overview.get("Wallet", ""))
    c.assets_b = _parse_isk_b(overview.get("Assets", ""))
    return c


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


# Map English month abbreviation → number
MONTH_ABBRS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ─── DATA COLLECTION ORCHESTRATION ────────────────────────────────────────────
def collect_corp(client: SoBClient, corp_id: int, corp_name: str, year: int,
                 years_back: int = 2, log_fn=None) -> Corp:
    """
    Build a Corp with full member roster + FAT data.

    1. Get list of mains from Character Finder (filtered by corp name on col[7])
    2. Fan-out: fetch Overview card + ESI corp join date for each main concurrently
    3. Fan-out: fetch all (year, month) FAT pages concurrently, then attribute

    log_fn(msg, tag) — optional callable for GUI progress (tag = colour name).
    Defaults to print() when not supplied.
    """
    def log(msg: str, tag: str = "white"):
        if log_fn:
            log_fn(msg, tag)
        else:
            print(msg)

    log(f"  [+] Collecting {corp_name} (ID {corp_id})...", "cyan")
    corp = Corp(corp_id=corp_id, name=corp_name)

    # 1. Mains (uses cached character_finder internally)
    mains = client.list_corp_mains(corp_name)
    log(f"      found {len(mains)} mains", "grey")
    if not mains:
        return corp

    # 2a. Corp's SOB alliance join date — one ESI call (cached 24 h)
    corp_alliance_join = get_corp_alliance_join_date(corp_id)
    if corp_alliance_join:
        log(f"      corp joined SOB: {corp_alliance_join}", "grey")

    # 2b. Fan-out: overview + join date for all mains concurrently
    def _fetch_one(ch: Character) -> Character:
        try:
            overview = client.character_overview(ch.pk)   # cached 24 h
            merged = character_from_overview(ch.pk, overview)
            merged.corp_id = corp_id
            merged.corp_name = corp_name
            merged.eve_id = ch.eve_id
            if not merged.alliance_name:
                merged.alliance_name = ch.alliance_name
            ch.__dict__.update(merged.__dict__)
        except Exception as e:
            log(f"      ! overview {ch.name}: {e}", "red")
        if ch.eve_id:
            char_corp_join = get_char_corp_join_date(ch.eve_id, corp_id)  # cached 24 h
            ch.join_date, ch.time_in_corp = compute_alliance_tenure(
                char_corp_join, corp_alliance_join
            )
        return ch

    log(f"      fetching overviews ({len(mains)} chars, {AUTH_WORKERS} workers)…", "grey")
    with ThreadPoolExecutor(max_workers=AUTH_WORKERS) as pool:
        mains = list(pool.map(_fetch_one, mains))

    # 3. Fan-out: all (year, month) FAT pages at once, then merge results
    today = date.today()
    fat_tasks: list[tuple[int, int]] = []
    for y in range(year - years_back, year + 1):
        max_month = 12 if y < today.year else today.month
        for m in range(1, max_month + 1):
            fat_tasks.append((y, m))

    log(f"      fetching {len(fat_tasks)} FAT months ({AUTH_WORKERS} workers)…", "grey")
    fat_results: dict[tuple[int, int], dict[str, int]] = {}
    with ThreadPoolExecutor(max_workers=AUTH_WORKERS) as pool:
        future_map = {
            pool.submit(client.corp_fat_month, corp_id, y, m): (y, m)
            for y, m in fat_tasks
        }
        for future in as_completed(future_map):
            ym = future_map[future]
            try:
                fat_results[ym] = future.result()
            except Exception:
                fat_results[ym] = {}

    # Apply FAT results to characters
    by_name = {ch.name: ch for ch in mains}
    for y in range(year - years_back, year + 1):
        max_month = 12 if y < today.year else today.month
        year_totals: dict[str, int] = {}
        for m in range(1, max_month + 1):
            for char_name, cnt in fat_results.get((y, m), {}).items():
                year_totals[char_name] = year_totals.get(char_name, 0) + cnt
                ch = by_name.get(char_name)
                if ch:
                    key = f"{y}-{MONTH_ABBRS[m - 1]}"
                    ch.fats_by_month[key] = ch.fats_by_month.get(key, 0) + cnt
        for char_name, total in year_totals.items():
            ch = by_name.get(char_name)
            if ch:
                ch.fats_by_year[y] = ch.fats_by_year.get(y, 0) + total

    # 4. Total FATs across window
    for ch in mains:
        ch.total_fats = sum(ch.fats_by_year.values())

    corp.members = mains
    return corp


# ─── REPORT BUILDER ───────────────────────────────────────────────────────────
class ReportBuilder:
    """Generates audit xlsx matching the exact styling of mineski_infinity_audit.xlsx."""

    def __init__(self, title: str, subtitle: str, members: list[Character], year: int):
        self.title_text = title
        self.subtitle = subtitle
        self.members = sorted(members, key=lambda c: -c.total_fats)
        self.year = year

    # ── Sheet 1: ROSTER ───────────────────────────────────────────────────────
    def _roster(self, ws):
        ws.title = "ROSTER"
        ws.sheet_properties.tabColor = C_CYAN
        ws.sheet_view.showGridLines = False

        ws.row_dimensions[1].height = 8
        ws.row_dimensions[2].height = 38
        ws.row_dimensions[3].height = 22
        ws.row_dimensions[4].height = 8
        ws.row_dimensions[5].height = 30

        ws.merge_cells("A2:N2")
        t = ws["A2"]
        t.value = f"◈  {self.title_text}  ·  CORP AUDIT REPORT  ◈"
        t.font = Font(name="Calibri", color=C_CYAN, size=20, bold=True)
        t.fill = fill(C_BG_DARK)
        t.alignment = align("center")

        ws.merge_cells("A3:N3")
        s = ws["A3"]
        s.value = self.subtitle
        s.font = Font(name="Calibri", color=C_GREY_TEXT, size=10)
        s.fill = fill(C_BG_DARK)
        s.alignment = align("center")

        # Columns: # | PILOT NAME | JOINED | IN ALLIANCE | SP (M) | LAST LOGIN |
        #          SEC STATUS | LOCATION | TOTAL FATs | JAN | FEB | MAR | APR | RATING
        HEADERS = [
            "#", "PILOT NAME", "JOINED\n(CORP)", "IN ALLIANCE", "SP (M)",
            "LAST LOGIN", "SEC\nSTATUS", "LOCATION", "TOTAL\nFATs",
            f"JAN '{str(self.year)[-2:]}", f"FEB '{str(self.year)[-2:]}",
            f"MAR '{str(self.year)[-2:]}", f"APR '{str(self.year)[-2:]}", "RATING"
        ]
        COL_WIDTHS = [4, 22, 13, 20, 8, 18, 7, 30, 7, 7, 7, 7, 7, 10]

        for col_idx, (hdr, width) in enumerate(zip(HEADERS, COL_WIDTHS), start=1):
            cell = ws.cell(row=5, column=col_idx, value=hdr)
            cell.font = Font(name="Calibri", color=C_CYAN, size=9, bold=True)
            cell.fill = fill(C_HEADER_BG)
            cell.alignment = align("center", wrap=True)
            cell.border = BORDER
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        for i, m in enumerate(self.members):
            row = 6 + i
            ws.row_dimensions[row].height = 16

            if m.total_fats >= 8:
                tier, tier_color = "★ ELITE", C_TEAL
            elif m.total_fats >= 4:
                tier, tier_color = "◆ ACTIVE", C_GREEN
            elif m.total_fats >= 1:
                tier, tier_color = "▷ PARTIAL", C_GOLD
            else:
                tier, tier_color = "○ GHOST", C_RED_DARK

            alt = C_BG_MID if i % 2 == 0 else C_BG_LIGHT

            def dcell(col, value, color=C_WHITE, bold=False, h="center"):
                c = ws.cell(row=row, column=col, value=value)
                c.font = Font(name="Calibri", color=color, size=9, bold=bold)
                c.fill = fill(alt)
                c.alignment = align(h)
                c.border = BORDER
                return c

            jan = m.fats_by_month.get(f"{self.year}-Jan", m.fats_by_month.get(f"{self.year}-01", 0))
            feb = m.fats_by_month.get(f"{self.year}-Feb", m.fats_by_month.get(f"{self.year}-02", 0))
            mar = m.fats_by_month.get(f"{self.year}-Mar", m.fats_by_month.get(f"{self.year}-03", 0))
            apr = m.fats_by_month.get(f"{self.year}-Apr", m.fats_by_month.get(f"{self.year}-04", 0))

            # Col 1-7: index, name, joined, in alliance, SP, last login, sec status
            dcell(1, i + 1, C_GREY_TEXT)
            dcell(2, m.name, C_WHITE, bold=True, h="left")
            dcell(3, m.join_date or "—", C_GREY_TEXT)
            dcell(4, m.time_in_corp or m.born or "—", C_GREY_TEXT)
            sp_color = C_TEAL if m.skillpoints_m >= 80 else (C_GOLD if m.skillpoints_m >= 30 else C_WHITE)
            dcell(5, m.skillpoints_m if m.skillpoints_m else "—", sp_color)
            dcell(6, m.last_login or "—", C_GREY_TEXT)
            sec_color = C_RED_DARK if m.sec_status < 0 else (C_GOLD if m.sec_status < 2 else C_GREEN)
            dcell(7, round(m.sec_status, 1), sec_color, bold=(m.sec_status < 0))

            # Col 8-14: location, FATs total + monthly, rating
            dcell(8, m.location or "—", C_GREY_TEXT, h="left")
            fat_color = C_TEAL if m.total_fats >= 8 else (C_GREEN if m.total_fats >= 4 else (C_GOLD if m.total_fats >= 1 else C_RED_DARK))
            dcell(9, m.total_fats, fat_color, bold=True)
            dcell(10, jan, C_GREY_TEXT if jan == 0 else C_TEAL)
            dcell(11, feb, C_GREY_TEXT if feb == 0 else C_TEAL)
            dcell(12, mar, C_GREY_TEXT if mar == 0 else C_TEAL)
            dcell(13, apr, C_GREY_TEXT if apr == 0 else C_TEAL)

            rc = ws.cell(row=row, column=14, value=tier)
            rc.font = Font(name="Calibri", color=tier_color, size=9, bold=True)
            rc.fill = fill(alt)
            rc.alignment = align("center")
            rc.border = BORDER

        legend_row = 6 + len(self.members) + 2
        ws.merge_cells(f"A{legend_row}:N{legend_row}")
        lg = ws[f"A{legend_row}"]
        lg.value = ("★ ELITE (8+ FATs)  |  ◆ ACTIVE (4-7 FATs)  |  "
                    "▷ PARTIAL (1-3 FATs)  |  ○ GHOST (0 FATs)  |  "
                    "IN ALLIANCE = time since character joined corp OR corp joined SOB "
                    "(whichever is more recent)  |  Data: Member Audit + AFAT + ESI")
        lg.font = Font(name="Calibri", color=C_GREY_TEXT, size=8, italic=True)
        lg.fill = fill(C_BG_DARK)
        lg.alignment = align("center")

        ws.freeze_panes = "A6"

    # ── Sheet 2: SUMMARY ──────────────────────────────────────────────────────
    def _summary(self, wb):
        ws = wb.create_sheet("SUMMARY")
        ws.sheet_properties.tabColor = C_TEAL
        ws.sheet_view.showGridLines = False

        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 32
        ws.column_dimensions["C"].width = 5
        ws.column_dimensions["D"].width = 28
        ws.column_dimensions["E"].width = 28

        ws.row_dimensions[1].height = 8
        ws.row_dimensions[2].height = 36
        ws.merge_cells("A2:E2")
        t = ws["A2"]
        t.value = f"◈  {self.title_text}  ·  CORP STATISTICS SUMMARY  ◈"
        t.font = Font(name="Calibri", color=C_TEAL, size=18, bold=True)
        t.fill = fill(C_BG_DARK)
        t.alignment = align("center")

        def stat_row(row, label, value, val_color=C_WHITE):
            ws.row_dimensions[row].height = 18
            lc = ws.cell(row=row, column=1, value=label)
            lc.font = Font(name="Calibri", color=C_GREY_TEXT, size=10)
            lc.fill = fill(C_BG_MID if row % 2 == 0 else C_BG_LIGHT)
            lc.alignment = align("left")
            lc.border = BORDER
            vc = ws.cell(row=row, column=2, value=value)
            vc.font = Font(name="Calibri", color=val_color, size=10, bold=True)
            vc.fill = fill(C_BG_MID if row % 2 == 0 else C_BG_LIGHT)
            vc.alignment = align("left")
            vc.border = BORDER

        ws.row_dimensions[4].height = 22
        ws.merge_cells("A4:B4")
        h = ws["A4"]
        h.value = "CORP OVERVIEW"
        h.font = Font(name="Calibri", color=C_CYAN, size=11, bold=True)
        h.fill = fill(C_HEADER_BG)
        h.alignment = align("center")

        n_mains = len(self.members)
        active = sum(1 for m in self.members if "hr" in m.last_login.lower() or ("day" in m.last_login.lower() and "month" not in m.last_login.lower()))
        any_fats = sum(1 for m in self.members if m.total_fats > 0)
        ghosts = n_mains - any_fats
        total_fats = sum(m.total_fats for m in self.members)
        ytd = sum(m.fats_by_year.get(self.year, 0) for m in self.members)

        stat_row(5,  "Total Mains",                n_mains, C_TEAL)
        stat_row(6,  "Members Active (<7 days)",   active, C_GREEN)
        stat_row(7,  "Members with ANY FATs",      any_fats, C_GOLD)
        stat_row(8,  "Ghost Members (0 FATs)",     ghosts, C_RED_DARK)
        stat_row(9,  "FAT Participation Rate",     f"{(any_fats/n_mains*100 if n_mains else 0):.0f}%", C_GOLD)
        stat_row(10, "Total FATs (3-year window)", total_fats, C_TEAL)
        stat_row(11, f"FATs in {self.year - 1}",   sum(m.fats_by_year.get(self.year - 1, 0) for m in self.members), C_WHITE)
        stat_row(12, f"FATs {self.year} YTD",      ytd, C_TEAL)
        stat_row(13, "Audit Date",                 str(date.today()), C_GREY_TEXT)

        # Top 10
        ws.row_dimensions[17].height = 22
        ws.merge_cells("A17:B17")
        h2 = ws["A17"]
        h2.value = "🏆 TOP FAT PERFORMERS"
        h2.font = Font(name="Calibri", color=C_GOLD, size=11, bold=True)
        h2.fill = fill(C_HEADER_BG)
        h2.alignment = align("center")

        for i, m in enumerate(self.members[:10]):
            r = 18 + i
            ws.row_dimensions[r].height = 16
            nc = ws.cell(row=r, column=1, value=m.name)
            nc.font = Font(name="Calibri", color=C_WHITE, size=9, bold=(i == 0))
            nc.fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            nc.alignment = align("left")
            nc.border = BORDER
            fc = ws.cell(row=r, column=2, value=f"{m.total_fats} FATs")
            tier_c = C_TEAL if m.total_fats >= 8 else (C_GREEN if m.total_fats >= 4 else C_GOLD)
            fc.font = Font(name="Calibri", color=tier_c, size=9, bold=True)
            fc.fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            fc.alignment = align("center")
            fc.border = BORDER

        # Ghosts
        ws.row_dimensions[30].height = 22
        ws.merge_cells("A30:B30")
        h3 = ws["A30"]
        h3.value = "⚠ GHOST MEMBERS (0 FATs)"
        h3.font = Font(name="Calibri", color=C_RED_DARK, size=11, bold=True)
        h3.fill = fill(C_HEADER_BG)
        h3.alignment = align("center")

        ghosts_list = [m for m in self.members if m.total_fats == 0][:15]
        for i, m in enumerate(ghosts_list):
            r = 31 + i
            ws.row_dimensions[r].height = 16
            nc = ws.cell(row=r, column=1, value=m.name)
            nc.font = Font(name="Calibri", color=C_GREY_TEXT, size=9)
            nc.fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            nc.alignment = align("left")
            nc.border = BORDER
            tc = ws.cell(row=r, column=2, value=m.last_login or "—")
            tc.font = Font(name="Calibri", color=C_RED_DARK, size=9)
            tc.fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            tc.alignment = align("left")
            tc.border = BORDER

        # Right side: monthly trend
        ws.row_dimensions[4].height = 22
        ws.merge_cells("D4:E4")
        mh = ws["D4"]
        mh.value = f"MONTHLY FAT TREND ({self.year})"
        mh.font = Font(name="Calibri", color=C_CYAN, size=11, bold=True)
        mh.fill = fill(C_HEADER_BG)
        mh.alignment = align("center")

        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for i, mo in enumerate(month_labels[:4]):
            total = sum(m.fats_by_month.get(f"{self.year}-{mo}", 0) for m in self.members)
            r = 5 + i
            ws.row_dimensions[r].height = 16
            mc = ws.cell(row=r, column=4, value=f"{mo} '{str(self.year)[-2:]}")
            mc.font = Font(name="Calibri", color=C_GREY_TEXT, size=10)
            mc.fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            mc.alignment = align("left")
            mc.border = BORDER
            vc = ws.cell(row=r, column=5, value=total)
            vc.font = Font(name="Calibri", color=C_TEAL, size=10, bold=True)
            vc.fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            vc.alignment = align("center")
            vc.border = BORDER

    # ── Sheet 3: CHARTS ───────────────────────────────────────────────────────
    def _charts(self, wb):
        ws = wb.create_sheet("CHARTS")
        ws.sheet_properties.tabColor = C_GOLD
        ws.sheet_view.showGridLines = False

        ws.row_dimensions[1].height = 8
        ws.row_dimensions[2].height = 32
        ws.merge_cells("A2:Z2")
        t = ws["A2"]
        t.value = f"◈  {self.title_text}  ·  VISUAL ANALYTICS  ◈"
        t.font = Font(name="Calibri", color=C_GOLD, size=16, bold=True)
        t.fill = fill(C_BG_DARK)
        t.alignment = align("center")

        # Chart 1: top-20 FAT leaderboard
        ws.cell(row=4, column=1, value="Pilot").font = Font(color=C_CYAN, bold=True, size=9)
        ws.cell(row=4, column=2, value="FATs").font = Font(color=C_CYAN, bold=True, size=9)
        ws.cell(row=4, column=1).fill = fill(C_HEADER_BG)
        ws.cell(row=4, column=2).fill = fill(C_HEADER_BG)

        for i, m in enumerate(self.members[:20], start=5):
            ws.row_dimensions[i].height = 12
            ws.cell(row=i, column=1, value=m.name).font = Font(color=C_WHITE, size=8)
            ws.cell(row=i, column=1).fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            ws.cell(row=i, column=2, value=m.total_fats).font = Font(color=C_TEAL, size=8)
            ws.cell(row=i, column=2).fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)

        top_rows = min(20, len(self.members))
        bar = BarChart()
        bar.type = "bar"
        bar.title = "Fleet Activity (FAT) Leaderboard"
        bar.style = 10
        bar.y_axis.title = "Total FATs"
        bar.x_axis.title = "Pilot"
        bar.height = 14
        bar.width = 22
        bar.add_data(Reference(ws, min_col=2, min_row=4, max_row=4 + top_rows), titles_from_data=True)
        bar.set_categories(Reference(ws, min_col=1, min_row=5, max_row=4 + top_rows))
        ws.add_chart(bar, "D4")

        # Chart 2: monthly trend
        ws.cell(row=28, column=1, value="Month").font = Font(color=C_CYAN, bold=True, size=9)
        ws.cell(row=28, column=2, value="FATs").font = Font(color=C_CYAN, bold=True, size=9)
        ws.cell(row=28, column=1).fill = fill(C_HEADER_BG)
        ws.cell(row=28, column=2).fill = fill(C_HEADER_BG)

        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for i, mo in enumerate(month_labels, start=29):
            total = sum(m.fats_by_month.get(f"{self.year}-{mo}", 0) for m in self.members)
            ws.cell(row=i, column=1, value=f"{mo} '{str(self.year)[-2:]}").font = Font(color=C_WHITE, size=9)
            ws.cell(row=i, column=1).fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            ws.cell(row=i, column=2, value=total).font = Font(color=C_TEAL, size=9)
            ws.cell(row=i, column=2).fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)

        line = LineChart()
        line.title = f"Monthly FAT Trend ({self.year})"
        line.style = 10
        line.y_axis.title = "FATs"
        line.x_axis.title = "Month"
        line.height = 12
        line.width = 20
        line.add_data(Reference(ws, min_col=2, min_row=28, max_row=40), titles_from_data=True)
        line.set_categories(Reference(ws, min_col=1, min_row=29, max_row=40))
        ws.add_chart(line, "D28")

        # Chart 3: tier distribution pie
        ws.cell(row=44, column=1, value="Tier").font = Font(color=C_CYAN, bold=True, size=9)
        ws.cell(row=44, column=2, value="Count").font = Font(color=C_CYAN, bold=True, size=9)
        ws.cell(row=44, column=1).fill = fill(C_HEADER_BG)
        ws.cell(row=44, column=2).fill = fill(C_HEADER_BG)

        tiers = [
            ("★ Elite (8+ FATs)",    sum(1 for m in self.members if m.total_fats >= 8)),
            ("◆ Active (4-7 FATs)",  sum(1 for m in self.members if 4 <= m.total_fats < 8)),
            ("▷ Partial (1-3 FATs)", sum(1 for m in self.members if 1 <= m.total_fats < 4)),
            ("○ Ghost (0 FATs)",     sum(1 for m in self.members if m.total_fats == 0)),
        ]
        for i, (tier, cnt) in enumerate(tiers, start=45):
            ws.cell(row=i, column=1, value=tier).font = Font(color=C_WHITE, size=9)
            ws.cell(row=i, column=1).fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)
            ws.cell(row=i, column=2, value=cnt).font = Font(color=C_TEAL, size=9, bold=True)
            ws.cell(row=i, column=2).fill = fill(C_BG_MID if i % 2 == 0 else C_BG_LIGHT)

        pie = PieChart()
        pie.title = "Member Activity Distribution"
        pie.style = 10
        pie.height = 12
        pie.width = 14
        pie.add_data(Reference(ws, min_col=2, min_row=44, max_row=48), titles_from_data=True)
        pie.set_categories(Reference(ws, min_col=1, min_row=45, max_row=48))
        ws.add_chart(pie, "D44")

        # Paint empty cells with dark background
        for row in ws.iter_rows():
            for cell in row:
                if not cell.fill.patternType:
                    cell.fill = fill(C_BG_DARK)

    def build(self) -> Workbook:
        wb = Workbook()
        self._roster(wb.active)
        self._summary(wb)
        self._charts(wb)
        wb.active = wb["ROSTER"]
        return wb


# ─── ALLIANCE MULTI-SHEET BUILDER ────────────────────────────────────────────
def _safe_sheet_name(name: str) -> str:
    """Excel sheet names: max 31 chars, no special chars."""
    cleaned = re.sub(r"[\\/*?:\[\]]", "", name)
    return cleaned[:31].strip()


def build_alliance_workbook(corps: list[Corp], year: int) -> Workbook:
    """
    Build a single workbook with:
      Sheet 1 — ALLIANCE SUMMARY (all corps ranked by total FATs)
      Sheet N — one ROSTER per corp (same styling as single-corp report)
    """
    wb = Workbook()
    all_members = [ch for corp in corps for ch in corp.members]

    # ── Sheet 1: Alliance Summary ─────────────────────────────────────────────
    ws = wb.active
    ws.title = "ALLIANCE SUMMARY"
    ws.sheet_properties.tabColor = C_GOLD
    ws.sheet_view.showGridLines = False

    ws.row_dimensions[1].height = 8
    ws.row_dimensions[2].height = 38
    ws.row_dimensions[3].height = 22

    ws.merge_cells("A2:I2")
    t = ws["A2"]
    t.value = "◈  SONS OF BANE  ·  ALLIANCE AUDIT REPORT  ◈"
    t.font = Font(name="Calibri", color=C_GOLD, size=20, bold=True)
    t.fill = fill(C_BG_DARK)
    t.alignment = align("center")

    ws.merge_cells("A3:I3")
    s = ws["A3"]
    s.value = (f"Sons of Bane Alliance  ·  EVE Online  ·  Audit Date: {date.today()}  ·  "
               f"{len(corps)} Corps  ·  {len(all_members)} Mains")
    s.font = Font(name="Calibri", color=C_GREY_TEXT, size=10)
    s.fill = fill(C_BG_DARK)
    s.alignment = align("center")

    # Corp summary table
    CORP_HEADERS = ["#", "CORPORATION", "MAINS", "TOTAL FATs", f"{year} FATs",
                    "★ ELITE", "◆ ACTIVE", "▷ PARTIAL", "○ GHOST"]
    CORP_WIDTHS  = [4,   32,            8,       10,           10,
                    8,       8,        9,         8]

    ws.row_dimensions[5].height = 28
    for ci, (hdr, w) in enumerate(zip(CORP_HEADERS, CORP_WIDTHS), start=1):
        c = ws.cell(row=5, column=ci, value=hdr)
        c.font = Font(name="Calibri", color=C_GOLD, size=9, bold=True)
        c.fill = fill(C_HEADER_BG)
        c.alignment = align("center", wrap=True)
        c.border = BORDER
        ws.column_dimensions[get_column_letter(ci)].width = w

    # Sort corps by total FATs descending
    sorted_corps = sorted(corps, key=lambda c: -sum(m.total_fats for m in c.members))
    for ri, corp in enumerate(sorted_corps):
        row = 6 + ri
        ws.row_dimensions[row].height = 16
        ms = corp.members
        n_mains = len(ms)
        total_fats = sum(m.total_fats for m in ms)
        year_fats  = sum(m.fats_by_year.get(year, 0) for m in ms)
        elite   = sum(1 for m in ms if m.total_fats >= 8)
        active  = sum(1 for m in ms if 4 <= m.total_fats < 8)
        partial = sum(1 for m in ms if 1 <= m.total_fats < 4)
        ghost   = sum(1 for m in ms if m.total_fats == 0)
        alt = C_BG_MID if ri % 2 == 0 else C_BG_LIGHT

        def cpcell(col, value, color=C_WHITE, bold=False):
            c = ws.cell(row=row, column=col, value=value)
            c.font = Font(name="Calibri", color=color, size=9, bold=bold)
            c.fill = fill(alt)
            c.alignment = align("center")
            c.border = BORDER
            return c

        cpcell(1, ri + 1, C_GREY_TEXT)
        cn = ws.cell(row=row, column=2, value=corp.name)
        cn.font = Font(name="Calibri", color=C_WHITE, size=9, bold=True)
        cn.fill = fill(alt); cn.alignment = align("left"); cn.border = BORDER
        cpcell(3, n_mains, C_WHITE)
        fat_col = C_TEAL if total_fats >= 50 else (C_GREEN if total_fats >= 20 else C_WHITE)
        cpcell(4, total_fats, fat_col, bold=True)
        cpcell(5, year_fats, C_TEAL if year_fats > 0 else C_GREY_TEXT)
        cpcell(6, elite,   C_TEAL   if elite   > 0 else C_GREY_TEXT)
        cpcell(7, active,  C_GREEN  if active  > 0 else C_GREY_TEXT)
        cpcell(8, partial, C_GOLD   if partial > 0 else C_GREY_TEXT)
        cpcell(9, ghost,   C_RED_DARK if ghost > 0 else C_GREY_TEXT)

    ws.freeze_panes = "A6"

    # ── Per-corp ROSTER sheets ────────────────────────────────────────────────
    for corp in sorted_corps:
        if not corp.members:
            continue
        rb = ReportBuilder(
            title=corp.name.upper(),
            subtitle=(f"Sons of Bane Alliance  ·  EVE Online  ·  "
                      f"Audit Date: {date.today()}  ·  {len(corp.members)} Mains"),
            members=corp.members,
            year=year,
        )
        corp_ws = wb.create_sheet()
        rb._roster(corp_ws)
        corp_ws.title = _safe_sheet_name(corp.name)  # set after _roster (which resets to "ROSTER")

    return wb


# ─── MAIN ENTRYPOINT ──────────────────────────────────────────────────────────
def _safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_").lower() or "report"


def run_character(client: SoBClient, name: str, year: int, out_dir: Path):
    print(f"[ Character mode ] {name}")
    rows = client.character_finder()  # global query, no corp filter
    match = None
    for r in rows:
        if len(r) < 13:
            continue
        pk, char_name = SoBClient._parse_finder_name_cell(r[0])
        if pk and char_name.lower() == name.lower():
            match = (pk, char_name, r)
            break
    if not match:
        print(f"ERROR: no character matching '{name}' found in Character Finder")
        sys.exit(2)
    pk, char_name, row = match
    corp_name = _strip_html(row[7])
    corp_id = 0  # not directly in finder; resolve from alliance corp list

    overview = client.character_overview(pk)
    ch = character_from_overview(pk, overview)
    ch.corp_name = corp_name

    # Find corp_id by matching name in alliance listing
    today = date.today()
    try:
        corps = client.list_alliance_corps(today.year, today.month)
        for cid, cname in corps:
            if cname.strip().lower() == corp_name.strip().lower():
                corp_id = cid
                break
    except Exception:
        pass

    if corp_id:
        # Pull this character's per-month FATs across the year
        for month in range(1, today.month + 1 if year == today.year else 13):
            mdata = client.corp_fat_month(corp_id, year, month)
            if ch.name in mdata:
                key = f"{year}-{MONTH_ABBRS[month - 1]}"
                ch.fats_by_month[key] = mdata[ch.name]
        ch.fats_by_year[year] = sum(ch.fats_by_month.values())
        ch.total_fats = ch.fats_by_year[year]

    ch.corp_id = corp_id

    rb = ReportBuilder(
        title=ch.name.upper(),
        subtitle=f"Sons of Bane Alliance  ·  {corp_name}  ·  Audit Date: {date.today()}",
        members=[ch],
        year=year,
    )
    wb = rb.build()
    out_path = out_dir / f"sob_character_{_safe_filename(ch.name)}_{date.today()}.xlsx"
    wb.save(out_path)
    print(f"[ OK ] {out_path}")
    return out_path


def run_corp(client: SoBClient, corp_identifier: str, year: int, out_dir: Path) -> Path:
    today = date.today()
    # Resolve corp ID if a name was passed
    if corp_identifier.isdigit():
        corp_id = int(corp_identifier)
        # Fetch corp name from the AFAT yearly stats page title
        try:
            r = client._get(f"/fleet-activity-tracking/statistics/corporation/{corp_id}/{year}/")
            soup = BeautifulSoup(r.text, "lxml")
            h = soup.find(["h1", "h2", "h3"])
            corp_name = h.get_text(strip=True) if h else f"Corp {corp_id}"
            # Strip trailing " Fleet Activity Tracking Statistics" if present
            corp_name = re.sub(r"\s*Fleet Activity Tracking.*$", "", corp_name).strip()
        except Exception:
            corp_name = f"Corp {corp_id}"
    else:
        corps = client.list_alliance_corps(today.year, today.month)
        match = next((c for c in corps if corp_identifier.lower() in c[1].lower()), None)
        if not match:
            print(f"ERROR: corp '{corp_identifier}' not found in SONS of BANE alliance")
            sys.exit(2)
        corp_id, corp_name = match

    print(f"[ Corp mode ] {corp_name} (ID {corp_id})")
    corp = collect_corp(client, corp_id, corp_name, year)

    rb = ReportBuilder(
        title=corp_name.upper(),
        subtitle=f"Sons of Bane Alliance  ·  EVE Online  ·  Audit Date: {date.today()}  ·  {len(corp.members)} Mains",
        members=corp.members,
        year=year,
    )
    wb = rb.build()
    out_path = out_dir / f"sob_corp_{_safe_filename(corp_name)}_{date.today()}.xlsx"
    wb.save(out_path)
    print(f"[ OK ] {out_path}")
    return out_path


def run_alliance(client: SoBClient, year: int, out_dir: Path):
    """
    Collect all corps and produce ONE workbook with:
      - Sheet 1: Alliance Summary (all corps ranked)
      - Sheet per corp: ROSTER in the same sci-fi format
    """
    print("[ Alliance mode ] SONS of BANE (all corps)")
    today = date.today()
    corp_list = client.list_alliance_corps(today.year, today.month)
    print(f"  Discovered {len(corp_list)} corps")

    corps: list[Corp] = []
    for corp_id, corp_name in corp_list:
        try:
            corp = collect_corp(client, corp_id, corp_name, year)
            corps.append(corp)
            print(f"  [ OK ] {corp_name}  ({len(corp.members)} mains)")
        except Exception as e:
            print(f"  ! {corp_name} failed: {e}")

    wb = build_alliance_workbook(corps, year)
    out_path = out_dir / f"sob_alliance_{date.today()}.xlsx"
    wb.save(out_path)
    print(f"[ OK ] Alliance report: {out_path}")
    return out_path


def main():
    p = argparse.ArgumentParser(
        description="SONS of BANE Alliance Auth compliance audit report generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See .env.example for authentication setup.",
    )
    def add_common(parser):
        parser.add_argument("--year", type=int, default=date.today().year,
                            help="Year to focus the FAT statistics on")
        parser.add_argument("--out", type=Path,
                            default=Path(__file__).parent / "reports",
                            help="Output directory")
        parser.add_argument("--env", type=Path, default=None,
                            help="Path to .env file (default: ./.env)")

    add_common(p)
    sub = p.add_subparsers(dest="mode", required=True)

    pc = sub.add_parser("character", help="Audit a single character by name")
    pc.add_argument("name", help="Character name (exact match)")
    add_common(pc)

    pr = sub.add_parser("corp", help="Audit a single corp by name or ID")
    pr.add_argument("identifier", help="Corp name (partial match) or corp ID")
    add_common(pr)

    pa = sub.add_parser("alliance", help="Audit all 24 SONS of BANE corps")
    add_common(pa)

    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    env = load_env(args.env)
    client = SoBClient(env)

    if args.mode == "character":
        run_character(client, args.name, args.year, args.out)
    elif args.mode == "corp":
        run_corp(client, args.identifier, args.year, args.out)
    elif args.mode == "alliance":
        run_alliance(client, args.year, args.out)


if __name__ == "__main__":
    main()
