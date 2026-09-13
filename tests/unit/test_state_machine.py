from __future__ import annotations

import pytest

from project_fifty.domain.models import OrderStatus
from project_fifty.execution.state_machine import OrderStateMachine


def test_valid_state_machine_path() -> None:
    machine = OrderStateMachine()
    machine.transition(OrderStatus.VALIDATED)
    machine.transition(OrderStatus.SUBMITTING)
    machine.transition(OrderStatus.FILLED)
    assert machine.status == OrderStatus.FILLED


def test_invalid_state_machine_transition_rejected() -> None:
    machine = OrderStateMachine()
    with pytest.raises(ValueError):
        machine.transition(OrderStatus.FILLED)
