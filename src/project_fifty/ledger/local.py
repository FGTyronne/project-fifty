from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from project_fifty.domain.models import LedgerEvent


class LocalAppendOnlyLedger:
    def __init__(self, path: Path | None = None) -> None:
        self._events: list[LedgerEvent] = []
        self._path = path
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                self._path.touch()

    def append(self, event_type: str, payload: dict[str, object]) -> LedgerEvent:
        event = LedgerEvent(
            event_id=str(uuid4()),
            sequence=len(self._events) + 1,
            event_type=event_type,
            payload=payload,
        )
        self._events.append(event)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")
        return event

    def all_events(self) -> list[LedgerEvent]:
        return list(self._events)
