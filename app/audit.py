"""
Audit orchestrator — coordinates all providers to build a Corp object.

Flow:
  1. AllianceAuthProvider supplies the member list, overview data, and FAT counts.
  2. ESIProvider enriches with corp/alliance join dates.
  3. Any registered EXTRA_PROVIDERS get a chance to enrich further (future sources).
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from app.models import Corp
from app.providers.auth_scraper import AllianceAuthProvider
from app.providers.base import BaseProvider
from app.providers.esi import ESIProvider


def collect_corp(
    auth: AllianceAuthProvider,
    esi: ESIProvider,
    extra_providers: list[BaseProvider],
    corp_id: int,
    corp_name: str,
    year: int,
    log: Callable[[str, str], None] = print,
) -> Corp:
    """
    Build a fully-enriched Corp for the given corp.

    Calls each provider in turn; all enrichment is done in-place on the
    character list.  extra_providers is the hook for future data sources.
    """
    log(f"  [+] Collecting {corp_name} (ID {corp_id})…", "cyan")
    corp = Corp(corp_id=corp_id, name=corp_name)

    members = auth.list_corp_members(corp_name)
    log(f"      found {len(members)} mains", "grey")
    if not members:
        return corp

    auth.enrich_characters(members, corp_id, corp_name, year, log)
    esi.enrich_characters(members, corp_id, corp_name, year, log)

    for provider in extra_providers:
        try:
            log(f"      [{provider.name}] enriching…", "grey")
            provider.enrich_characters(members, corp_id, corp_name, year, log)
        except Exception as e:
            log(f"      [{provider.name}] failed: {e}", "red")

    corp.members = members
    log(f"  [✓] {corp_name} — {len(members)} members collected", "green")
    return corp


def collect_alliance(
    auth: AllianceAuthProvider,
    esi: ESIProvider,
    extra_providers: list[BaseProvider],
    year: int,
    log: Callable[[str, str], None] = print,
) -> list[Corp]:
    today = date.today()
    corp_list = auth.list_alliance_corps(today.year, today.month)
    log(f"  Discovered {len(corp_list)} corps in SONS of BANE", "cyan")

    corps: list[Corp] = []
    for corp_id, corp_name in corp_list:
        try:
            corp = collect_corp(auth, esi, extra_providers, corp_id, corp_name, year, log)
            corps.append(corp)
        except Exception as e:
            log(f"  ! {corp_name} failed: {e}", "red")

    return corps
