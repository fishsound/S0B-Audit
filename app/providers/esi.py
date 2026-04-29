"""
ESI provider — public EVE Swagger Interface calls.
Adds corp join date and alliance tenure to each character.
No authentication required.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Callable, Optional

import requests

from app.cache import cache
from app.config import ESI_BASE, ESI_WORKERS, SOB_ALLIANCE_ID, TTL_ESI, USER_AGENT
from app.models import Character
from app.providers.base import BaseProvider

_ESI_RETRY_DELAYS = (1, 2, 4)  # seconds between retries on 5xx / network errors


def _esi_get(path: str) -> dict | list:
    url = f"{ESI_BASE}{path}"
    last_err = None
    for attempt, delay in enumerate((*_ESI_RETRY_DELAYS, None)):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            if r.status_code == 200:
                return r.json()
            if r.status_code < 500:
                return []
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        if delay is not None:
            time.sleep(delay)
    return []


def _format_duration(start: date) -> str:
    total_days = (date.today() - start).days
    years = total_days // 365
    months = (total_days % 365) // 30
    days = total_days % 30
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years > 1 else ''}")
    if months:
        parts.append(f"{months} month{'s' if months > 1 else ''}")
    if not parts:
        parts.append(f"{days} day{'s' if days > 1 else ''}")
    return ", ".join(parts[:2])


class ESIProvider(BaseProvider):
    name = "esi"
    requires_auth = False

    def _char_corp_join(self, eve_id: int, corp_id: int) -> Optional[date]:
        cache_key = f"esi_char:{eve_id}:{corp_id}"
        cached = cache.get(cache_key, TTL_ESI)
        if cached is not None:
            return date.fromisoformat(cached) if cached != "__none__" else None

        result: Optional[date] = None
        history = _esi_get(f"/v2/characters/{eve_id}/corporationhistory/")
        for entry in reversed(history):
            if entry.get("corporation_id") == corp_id:
                result = datetime.fromisoformat(
                    entry["start_date"].replace("Z", "+00:00")
                ).date()
                break

        cache.set(cache_key, result.isoformat() if result else "__none__")
        return result

    def _corp_alliance_join(self, corp_id: int) -> Optional[date]:
        cache_key = f"esi_corp:{corp_id}"
        cached = cache.get(cache_key, TTL_ESI)
        if cached is not None:
            return date.fromisoformat(cached) if cached != "__none__" else None

        result: Optional[date] = None
        history = _esi_get(f"/v2/corporations/{corp_id}/alliancehistory/")
        for entry in reversed(history):
            if entry.get("alliance_id") == SOB_ALLIANCE_ID:
                result = datetime.fromisoformat(
                    entry["start_date"].replace("Z", "+00:00")
                ).date()
                break

        cache.set(cache_key, result.isoformat() if result else "__none__")
        return result

    def enrich_characters(
        self,
        chars: list[Character],
        corp_id: int,
        corp_name: str,
        year: int,
        log: Callable[[str, str], None],
    ) -> None:
        corp_join = self._corp_alliance_join(corp_id)
        if corp_join:
            log(f"      corp joined SoB alliance: {corp_join}", "grey")

        def _fetch_one(ch: Character) -> Character:
            if not ch.eve_id:
                return ch
            char_join = self._char_corp_join(ch.eve_id, corp_id)
            if not char_join:
                ch.join_date = "—"
                ch.time_in_corp = "—"
                return ch
            ch.join_date = char_join.strftime("%Y-%b-%d")
            effective = max(char_join, corp_join) if corp_join else char_join
            ch.time_in_corp = _format_duration(effective)
            return ch

        log(f"      fetching ESI join dates ({len(chars)} chars)…", "grey")
        with ThreadPoolExecutor(max_workers=ESI_WORKERS) as pool:
            chars[:] = list(pool.map(_fetch_one, chars))
