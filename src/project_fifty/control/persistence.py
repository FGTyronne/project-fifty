from __future__ import annotations

from pydantic import PrivateAttr

from project_fifty.control.state import ControlState
from project_fifty.domain.models import ExperimentMode
from project_fifty.ledger.base import Ledger

CONTROL_MODE_EVENT = "control_mode_changed"


def _restored_mode(ledger: Ledger) -> ExperimentMode:
    mode = ExperimentMode.NORMAL
    for event in ledger.all_events():
        if event.event_type != CONTROL_MODE_EVENT:
            continue
        raw = event.payload.get("to")
        if not isinstance(raw, str):
            raise ValueError("persisted control-mode event is missing target mode")
        mode = ExperimentMode(raw)
    return mode


def restore_control_state(*, ledger: Ledger, kill_switch_active: bool = False) -> ControlState:
    return ControlState(mode=_restored_mode(ledger), kill_switch_active=kill_switch_active)


class LedgerBackedControlState(ControlState):
    """Control state whose mode transitions survive process restarts.

    The transition event is written before process-local mutation. A crash in between therefore
    restores the stricter durable target state on the next runtime rather than silently returning
    to NORMAL.
    """

    _ledger: Ledger = PrivateAttr()

    def __init__(self, *, ledger: Ledger, **data: object) -> None:
        super().__init__(**data)
        self._ledger = ledger

    @classmethod
    def restore(
        cls,
        *,
        ledger: Ledger,
        kill_switch_active: bool = False,
    ) -> "LedgerBackedControlState":
        return cls(
            ledger=ledger,
            mode=_restored_mode(ledger),
            kill_switch_active=kill_switch_active,
        )

    def transition_mode(self, next_mode: ExperimentMode, *, automatic: bool = False) -> None:
        previous = self.mode
        if previous == next_mode:
            return
        if previous == ExperimentMode.DEAD and next_mode != ExperimentMode.DEAD:
            raise ValueError("DEAD mode is terminal for this experiment")
        self._ledger.append(
            CONTROL_MODE_EVENT,
            {
                "from": previous.value,
                "to": next_mode.value,
                "reason": "automatic" if automatic else "explicit",
                "automatic": automatic,
            },
        )
        super().transition_mode(next_mode, automatic=automatic)


def transition_control_state(
    *,
    ledger: Ledger,
    control: ControlState,
    next_mode: ExperimentMode,
    reason: str,
    automatic: bool = True,
) -> None:
    previous = control.mode
    if previous == next_mode:
        return
    if previous == ExperimentMode.DEAD and next_mode != ExperimentMode.DEAD:
        raise ValueError("DEAD mode is terminal for this experiment")

    ledger.append(
        CONTROL_MODE_EVENT,
        {
            "from": previous.value,
            "to": next_mode.value,
            "reason": reason,
            "automatic": automatic,
        },
    )
    # Avoid double-writing when the caller supplied the ledger-backed implementation.
    if isinstance(control, LedgerBackedControlState):
        ControlState.transition_mode(control, next_mode, automatic=automatic)
    else:
        control.transition_mode(next_mode, automatic=automatic)


def persist_control_transition(
    *,
    ledger: Ledger,
    previous: ExperimentMode,
    control: ControlState,
    reason: str,
) -> None:
    """Compatibility helper for callers that already changed the in-memory control state."""
    if previous == control.mode:
        return
    ledger.append(
        CONTROL_MODE_EVENT,
        {
            "from": previous.value,
            "to": control.mode.value,
            "reason": reason,
            "automatic": True,
        },
    )
