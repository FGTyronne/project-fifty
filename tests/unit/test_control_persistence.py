from pathlib import Path

import pytest

from project_fifty.control.persistence import LedgerBackedControlState
from project_fifty.domain.models import ExperimentMode
from project_fifty.ledger.local import LocalAppendOnlyLedger


def test_safe_mode_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = LocalAppendOnlyLedger(path)
    control = LedgerBackedControlState.restore(ledger=ledger)

    control.transition_mode(ExperimentMode.SAFE, automatic=True)

    restored = LedgerBackedControlState.restore(ledger=LocalAppendOnlyLedger(path))
    assert restored.mode == ExperimentMode.SAFE


def test_dead_mode_survives_restart_and_remains_terminal(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = LocalAppendOnlyLedger(path)
    control = LedgerBackedControlState.restore(ledger=ledger)

    control.transition_mode(ExperimentMode.DEAD)
    restored = LedgerBackedControlState.restore(ledger=LocalAppendOnlyLedger(path))

    assert restored.mode == ExperimentMode.DEAD
    with pytest.raises(ValueError, match="terminal"):
        restored.transition_mode(ExperimentMode.NORMAL)


def test_kill_switch_is_runtime_authority_not_overwritten_by_ledger(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = LocalAppendOnlyLedger(path)
    first = LedgerBackedControlState.restore(ledger=ledger, kill_switch_active=False)
    first.transition_mode(ExperimentMode.SAFE, automatic=True)

    restored = LedgerBackedControlState.restore(
        ledger=LocalAppendOnlyLedger(path),
        kill_switch_active=True,
    )

    assert restored.mode == ExperimentMode.SAFE
    assert restored.kill_switch_active is True
