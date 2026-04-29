"""Central data models shared across all providers and the report builder."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Character:
    pk: int
    name: str
    eve_id: Optional[int] = None
    corp_name: str = ""
    corp_id: Optional[int] = None
    alliance_name: str = ""
    main_name: str = ""
    is_main: bool = False
    join_date: str = ""
    time_in_corp: str = ""
    born: str = ""
    skillpoints_m: float = 0.0
    last_login: str = ""
    sec_status: float = 0.0
    wallet_b: float = 0.0
    assets_b: float = 0.0
    location: str = ""
    ship: str = ""
    total_fats: int = 0
    fats_by_year: dict = field(default_factory=dict)
    fats_by_month: dict = field(default_factory=dict)
    # Extensible bucket — new providers write keyed sub-dicts here,
    # e.g. provider_data["zkillboard"] = {"kills": 42, "efficiency": 0.87}
    provider_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Corp:
    corp_id: int
    name: str
    members: list[Character] = field(default_factory=list)
