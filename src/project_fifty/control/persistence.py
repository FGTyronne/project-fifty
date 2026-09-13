from __future__ import annotations

from project_fifty.control.state import ControlState
from project_fifty.domain.models import ExperimentMode
from project_fifty.ledger.base import Ledger

CONTROL_MODE_EVENT = "control_mode_changed"


def restore_control_state(*, ledger: Ledger, kill_switch_active: bool = False) -> ControlState:
    mode = ExperimentMode.NORMAL
    for event in ledger.all_events():
        if event.event_type != CONTROL_MODE_EVENT:
            continue
        raw = event.payload.get("to")
        if not isinstance(raw, str):
            raise ValueError("persisted control-mode event is missing target mode")
        mode = ExperimentMode(raw)
    return ControlState(mode=mode, kill_switch_active=kill_switch_active)


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

    # Persist the conservative target state before mutating process-local state. If the process
    # dies between these two operations, the next runtime restores the stricter persisted mode.
    ledger.append(
        CONTROL_MODE_EVENT,
        {
            "from": previous.value,
            "to": next_mode.value,
            "reason": reason,
            "automatic": automatic,
        },
    )
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
