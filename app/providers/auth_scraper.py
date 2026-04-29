"""
Alliance Auth provider — scrapes auth.sonsofbane.com for:
  - Member Audit character data (overview cards)
  - AFAT fleet activity tracking (FAT counts)
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Callable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.cache import cache
from app.config import (
    AUTH_WORKERS, BASE_URL, MONTH_ABBRS, REQUEST_DELAY,
    SOB_ALLIANCE_ID, TTL_FAT_MONTH, TTL_FINDER, TTL_OVERVIEW, USER_AGENT,
)
from app.models import Character, Corp
from app.providers.base import BaseProvider


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


def _parse_isk_b(s: str) -> float:
    if not s:
        return 0.0
    s = s.replace("ISK", "").replace(",", "").strip()
    m = re.search(r"([-+]?\d+(?:\.\d+)?)", s)
    return round(float(m.group(1)) / 1e9, 2) if m else 0.0


def _parse_sp_m(s: str) -> float:
    """Parse skill-point string into millions (e.g. '99,875,432 SP' → 99.9)."""
    if not s:
        return 0.0
    s = s.replace("SP", "").replace(",", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return round(float(m.group(1)) / 1e6, 1) if m else 0.0


def _parse_sec(s: str) -> float:
    if not s:
        return 0.0
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else 0.0


class AllianceAuthProvider(BaseProvider):
    """Authenticated scraper for auth.sonsofbane.com."""

    name = "alliance_auth"
    requires_auth = True
    FINDER_PAGE_SIZE = 100

    def __init__(self, session_cookie: str, csrf_token: str):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        })
        cookie_str = f"sessionid={session_cookie}; csrftoken={csrf_token}"
        self._session.headers["Cookie"] = cookie_str
        self._session.headers["X-CSRFToken"] = csrf_token

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _get(self, path: str, **kwargs):
        url = urljoin(BASE_URL + "/", path.lstrip("/"))
        time.sleep(REQUEST_DELAY)
        r = self._session.get(url, timeout=30, **kwargs)
        if r.status_code == 302 or "login" in r.url.lower():
            raise RuntimeError(
                "Auth failed — session cookie has expired. "
                "Re-copy it from Chrome DevTools → Application → Cookies."
            )
        r.raise_for_status()
        return r

    # ── Character Finder ─────────────────────────────────────────────────────

    def _character_finder_raw(self, corp_name: str = "") -> list[list]:
        cache_key = f"finder:{corp_name}"
        cached = cache.get(cache_key, TTL_FINDER)
        if cached is not None:
            return cached

        all_rows, start = [], 0
        while True:
            params = {"draw": "1", "start": str(start), "length": str(self.FINDER_PAGE_SIZE)}
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

        cache.set(cache_key, all_rows)
        return all_rows

    @staticmethod
    def _parse_finder_name_cell(cell_html: str) -> tuple[Optional[int], str]:
        soup = BeautifulSoup(cell_html, "lxml")
        a = soup.find("a", href=re.compile(r"/member-audit/character_viewer/\d+/"))
        if not a:
            return None, ""
        m = re.search(r"/character_viewer/(\d+)/", a["href"])
        return (int(m.group(1)) if m else None), a.get_text(strip=True)

    def list_corp_members(self, corp_name: str) -> list[Character]:
        rows = self._character_finder_raw(corp_name=corp_name)
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

    def list_alliance_corps(self, year: int, month: int) -> list[tuple[int, str]]:
        cache_key = f"alliance_corps:{year}:{month}"
        cached = cache.get(cache_key, TTL_FINDER)
        if cached is not None:
            return [(int(r[0]), r[1]) for r in cached]

        r = self._get(
            f"/fleet-activity-tracking/statistics/alliance/{SOB_ALLIANCE_ID}/{year}/{month}/"
        )
        soup = BeautifulSoup(r.text, "lxml")
        corps: list[tuple[int, str]] = []
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

        cache.set(cache_key, corps)
        return corps

    # ── Overview ─────────────────────────────────────────────────────────────

    def _character_overview(self, pk: int) -> dict:
        cache_key = f"overview:{pk}"
        cached = cache.get(cache_key, TTL_OVERVIEW)
        if cached is not None:
            return cached

        r = self._get(f"/member-audit/character_viewer/{pk}/")
        soup = BeautifulSoup(r.text, "lxml")
        result = {}
        for dl in soup.select("dl.dl-horizontal"):
            for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
                key = dt.get_text(strip=True).rstrip(":").strip()
                if key:
                    result[key] = dd.get_text(" ", strip=True)
        h1 = soup.find(["h1", "h2"])
        if h1 and "Character" not in result:
            result["Character"] = h1.get_text(strip=True)

        cache.set(cache_key, result)
        return result

    def _overview_to_character(self, pk: int, overview: dict) -> Character:
        c = Character(
            pk=pk,
            name=overview.get("Character") or overview.get("Name") or f"char_{pk}",
        )
        c.corp_name = overview.get("Corporation", "")
        c.alliance_name = overview.get("Alliance", "")
        c.main_name = overview.get("Main", "")
        c.is_main = c.main_name == c.name or not c.main_name
        c.born = overview.get("Born", "")
        c.last_login = overview.get("Last Login", "")
        c.location = overview.get("Location", "") or overview.get("System", "")
        c.ship = overview.get("Ship", "")
        sp_raw = (
            overview.get("Skill Points")
            or overview.get("Skillpoints")
            or overview.get("Total Skill Points")
            or overview.get("SP")
            or next((v for k, v in overview.items()
                     if "skill" in k.lower() and "point" in k.lower()), "")
        )
        c.skillpoints_m = _parse_sp_m(sp_raw)
        c.sec_status = _parse_sec(overview.get("Sec. Status", ""))
        c.wallet_b = _parse_isk_b(overview.get("Wallet", ""))
        c.assets_b = _parse_isk_b(overview.get("Assets", ""))
        return c

    # ── AFAT ─────────────────────────────────────────────────────────────────

    def _corp_fat_month(self, corp_id: int, year: int, month: int) -> dict[str, int]:
        today = date.today()
        is_current = (year == today.year and month == today.month)
        cache_key = f"fat:{corp_id}:{year}:{month}"
        if not is_current:
            cached = cache.get(cache_key, TTL_FAT_MONTH)
            if cached is not None:
                return cached

        try:
            r = self._get(
                f"/fleet-activity-tracking/statistics/corporation/{corp_id}/{year}/{month}/"
            )
        except Exception:
            return {}

        soup = BeautifulSoup(r.text, "lxml")
        results: dict[str, int] = {}
        tables = soup.find_all("table")
        if not tables:
            return results
        tbody = tables[0].find("tbody")
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
            cache.set(cache_key, results)
        return results

    # ── Provider entry-point ──────────────────────────────────────────────────

    def enrich_characters(
        self,
        chars: list[Character],
        corp_id: int,
        corp_name: str,
        year: int,
        log: Callable[[str, str], None],
    ) -> None:
        """Fetch overview cards + FAT data and write into each character."""
        today = date.today()

        # Fan-out: overview for each main
        def _fetch_overview(ch: Character) -> Character:
            try:
                overview = self._character_overview(ch.pk)
                merged = self._overview_to_character(ch.pk, overview)
                merged.corp_id = corp_id
                merged.corp_name = corp_name
                merged.eve_id = ch.eve_id
                if not merged.alliance_name:
                    merged.alliance_name = ch.alliance_name
                ch.__dict__.update(merged.__dict__)
            except Exception as e:
                log(f"      ! overview {ch.name}: {e}", "red")
            return ch

        log(f"      fetching overviews ({len(chars)} chars)…", "grey")
        with ThreadPoolExecutor(max_workers=AUTH_WORKERS) as pool:
            chars[:] = list(pool.map(_fetch_overview, chars))

        # Fan-out: all FAT months for the 3-year window
        fat_tasks: list[tuple[int, int]] = []
        for y in range(year - 2, year + 1):
            max_month = 12 if y < today.year else today.month
            for m in range(1, max_month + 1):
                fat_tasks.append((y, m))

        log(f"      fetching {len(fat_tasks)} FAT months…", "grey")
        fat_results: dict[tuple[int, int], dict[str, int]] = {}
        with ThreadPoolExecutor(max_workers=AUTH_WORKERS) as pool:
            future_map = {
                pool.submit(self._corp_fat_month, corp_id, y, m): (y, m)
                for y, m in fat_tasks
            }
            for future in as_completed(future_map):
                ym = future_map[future]
                try:
                    fat_results[ym] = future.result()
                except Exception:
                    fat_results[ym] = {}

        # Apply FAT data
        by_name = {ch.name: ch for ch in chars}
        for y in range(year - 2, year + 1):
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

        for ch in chars:
            ch.total_fats = sum(ch.fats_by_year.values())
