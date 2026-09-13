from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.domain.models import PortfolioState
from project_fifty.strategies.baseline import RegimeState
from project_fifty.strategies.contracts import MarketBar, StrategyContext
from project_fifty.strategies.regime_persistent import RegimePersistentConfirmedStrategy


class StubRegimePersistentStrategy(RegimePersistentConfirmedStrategy):
    _mapping = {
        Decimal("101"): RegimeState.RISK_ON,
        Decimal("102"): RegimeState.NEUTRAL,
        Decimal("103"): RegimeState.RISK_OFF,
        Decimal("104"): RegimeState.SHOCK,
    }

    def _raw_regime_for_bars(self, bars: tuple[MarketBar, ...]) -> RegimeState:
        return self._mapping[bars[-1].close]


def _bar(timestamp: datetime, close: Decimal) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("1000000"),
    )


def _context(regimes: tuple[RegimeState, ...]) -> StrategyContext:
    mapping = {
        RegimeState.RISK_ON: Decimal("101"),
        RegimeState.NEUTRAL: Decimal("102"),
        RegimeState.RISK_OFF: Decimal("103"),
        RegimeState.SHOCK: Decimal("104"),
    }
    end = datetime(2025, 5, 19, 20, 0, tzinfo=UTC)
    start = end - timedelta(hours=len(regimes) - 1)
    spy = tuple(
        _bar(start + timedelta(hours=index), mapping[regime])
        for index, regime in enumerate(regimes)
    )
    aapl = (_bar(end, Decimal("100")),)
    return StrategyContext(
        as_of=end,
        currency="USD",
        portfolio=PortfolioState(
            cash=Decimal("67.6725"),
            positions={},
            nav=Decimal("67.6725"),
            currency="USD",
            as_of=end,
        ),
        reference_prices={"AAPL": Decimal("100")},
        reference_price_timestamps={"AAPL": end},
        market_state_hash="m7-regime-state",
        history={"SPY": spy, "AAPL": aapl},
        benchmark_symbol="SPY",
    )


def test_shock_is_immediate() -> None:
    diagnostics = StubRegimePersistentStrategy().regime_diagnostics(
        _context((RegimeState.RISK_ON, RegimeState.NEUTRAL, RegimeState.SHOCK))
    )

    assert diagnostics.raw_regime == RegimeState.SHOCK
    assert diagnostics.effective_regime == RegimeState.SHOCK
    assert diagnostics.reason == "SHOCK_EXIT"


def test_risk_off_is_immediate() -> None:
    diagnostics = StubRegimePersistentStrategy().regime_diagnostics(
        _context((RegimeState.RISK_ON, RegimeState.RISK_ON, RegimeState.RISK_OFF))
    )

    assert diagnostics.effective_regime == RegimeState.RISK_OFF
    assert diagnostics.reason == "RISK_OFF_IMMEDIATE"


def test_recovery_after_adverse_state_requires_three_non_adverse_bars() -> None:
    diagnostics = StubRegimePersistentStrategy().regime_diagnostics(
        _context((RegimeState.RISK_OFF, RegimeState.NEUTRAL, RegimeState.NEUTRAL))
    )

    assert diagnostics.raw_regime == RegimeState.NEUTRAL
    assert diagnostics.effective_regime == RegimeState.RISK_OFF
    assert diagnostics.reason == "RECOVERY_UNCONFIRMED"


def test_unconfirmed_risk_on_remains_neutral() -> None:
    diagnostics = StubRegimePersistentStrategy().regime_diagnostics(
        _context((RegimeState.NEUTRAL, RegimeState.RISK_ON, RegimeState.RISK_ON))
    )

    assert diagnostics.raw_regime == RegimeState.RISK_ON
    assert diagnostics.effective_regime == RegimeState.NEUTRAL
    assert diagnostics.reason == "RISK_ON_UNCONFIRMED"


def test_three_risk_on_bars_confirm_full_risk_on_regime() -> None:
    strategy = StubRegimePersistentStrategy()
    context = _context((RegimeState.RISK_ON,) * 3)

    diagnostics = strategy.regime_diagnostics(context)
    target = strategy.generate_target(context)

    assert diagnostics.effective_regime == RegimeState.RISK_ON
    assert diagnostics.reason == "RISK_ON_CONFIRMED"
    assert target.strategy_version == "4.0.0"
    assert target.evidence["raw_regime"] == "RISK_ON"
    assert target.evidence["effective_regime"] == "RISK_ON"
    assert target.evidence["recent_raw_regimes"] == "RISK_ON,RISK_ON,RISK_ON"


def test_three_non_adverse_mixed_bars_recover_to_neutral() -> None:
    diagnostics = StubRegimePersistentStrategy().regime_diagnostics(
        _context((RegimeState.NEUTRAL, RegimeState.RISK_ON, RegimeState.NEUTRAL))
    )

    assert diagnostics.effective_regime == RegimeState.NEUTRAL
    assert diagnostics.reason == "NEUTRAL_CONFIRMED"


def test_same_history_recomputes_same_effective_regime_after_restart() -> None:
    context = _context((RegimeState.RISK_OFF, RegimeState.NEUTRAL, RegimeState.NEUTRAL))

    first = StubRegimePersistentStrategy().regime_diagnostics(context)
    second = StubRegimePersistentStrategy().regime_diagnostics(context)

    assert first == second
