"""Abstract base class for audit data providers."""
from __future__ import annotations

from abc import ABC
from typing import Callable

from app.models import Character


class BaseProvider(ABC):
    """
    Contract for a data provider that enriches audit characters.

    Implement enrich_characters() to add data to character.provider_data[self.name].
    list_alliance_corps() and list_corp_members() only need overrides in the
    primary (Alliance Auth) provider.
    """

    name: str = "base"
    requires_auth: bool = False

    def list_alliance_corps(self, year: int, month: int) -> list[tuple[int, str]]:
        return []

    def list_corp_members(self, corp_name: str) -> list[Character]:
        return []

    def enrich_characters(
        self,
        chars: list[Character],
        corp_id: int,
        corp_name: str,
        year: int,
        log: Callable[[str, str], None],
    ) -> None:
        """Enrich characters in-place. Called once per corp audit."""
