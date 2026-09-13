from decimal import Decimal

import pytest

from project_fifty.backtest.engine import BacktestEngine
from project_fifty.strategies.baseline import RegimeAwareTechnicalStrategy


def test_backtest_clamps_only_microscopic_negative_cash_residue() -> None:
    assert BacktestEngine._clamp_cash(Decimal("-1e-26")) == Decimal("0")


def test_backtest_rejects_material_negative_cash() -> None:
    with pytest.raises(RuntimeError, match="materially more cash"):
        BacktestEngine._clamp_cash(Decimal("-0.000001"))


def test_backtest_keeps_positive_cash_unchanged() -> None:
    value = Decimal("0.000000000001")
    assert BacktestEngine._clamp_cash(value) == value


def test_backtest_engine_still_constructs_with_baseline_strategy() -> None:
    # Guards against the precision helper becoming a separate execution path.
    assert isinstance(BacktestEngine(RegimeAwareTechnicalStrategy()), BacktestEngine)
