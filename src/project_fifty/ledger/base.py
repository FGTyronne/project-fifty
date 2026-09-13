from __future__ import annotations

from typing import Protocol

from project_fifty.domain.models import LedgerEvent


class Ledger(Protocol):
    def append(self, event_type: str, payload: dict[str, object]) -> LedgerEvent: ...

    def all_events(self) -> list[LedgerEvent]: ...
