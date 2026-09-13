from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from project_fifty.domain.models import LedgerEvent

_GENESIS_HASH = "GENESIS"


def _hash_event_payload(
    *,
    sequence: int,
    event_type: str,
    payload: dict[str, object],
    created_at: datetime,
    prev_hash: str,
) -> str:
    canonical = {
        "sequence": sequence,
        "event_type": event_type,
        "payload": payload,
        "created_at": created_at.isoformat(),
        "prev_hash": prev_hash,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()


class LocalAppendOnlyLedger:
    def __init__(self, path: Path | None = None) -> None:
        self._events: list[LedgerEvent] = []
        self._path = path
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._load_existing_events()

    def _load_existing_events(self) -> None:
        assert self._path is not None
        expected_sequence = 1
        prev_hash = _GENESIS_HASH

        with self._path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                loaded = json.loads(line)
                event = LedgerEvent.model_validate(loaded)
                if event.sequence != expected_sequence:
                    raise ValueError("ledger sequence is non-monotonic")
                if event.prev_hash != prev_hash:
                    raise ValueError("ledger hash chain is invalid")

                expected_hash = _hash_event_payload(
                    sequence=event.sequence,
                    event_type=event.event_type,
                    payload=event.payload,
                    created_at=event.created_at,
                    prev_hash=event.prev_hash,
                )
                if event.event_hash != expected_hash:
                    raise ValueError("ledger event hash mismatch")

                self._events.append(event)
                expected_sequence += 1
                prev_hash = event.event_hash

    def append(self, event_type: str, payload: dict[str, object]) -> LedgerEvent:
        sequence = len(self._events) + 1
        prev_hash = self._events[-1].event_hash if self._events else _GENESIS_HASH
        created_at = datetime.now(UTC)
        event = LedgerEvent(
            event_id=str(uuid4()),
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            prev_hash=prev_hash,
            event_hash=_hash_event_payload(
                sequence=sequence,
                event_type=event_type,
                payload=payload,
                created_at=created_at,
                prev_hash=prev_hash,
            ),
            created_at=created_at,
        )
        self._events.append(event)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")
        return event

    def all_events(self) -> list[LedgerEvent]:
        return list(self._events)
