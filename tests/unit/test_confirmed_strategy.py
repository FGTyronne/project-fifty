from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.domain.models import PortfolioState, Position
from project_fifty.strategies.baseline import RegimeState, SignalBreakdown
from project_fifty.strategies.confirmed import (
    ConfirmedPersistentConfig,
    ConfirmedPersistentRegimeTechnicalStrategy,
)
from project_fifty.strategies.contracts import MarketBar, StrategyContext


class StubConfirmedStrategy(ConfirmedPersistentRegimeTechnicalStrategy):
    def _detect_regime(self, context: StrategyContext) -> RegimeState:
        return RegimeState.RISK_ON

    def _score_symbol(
        self,
        symbol: str,
        bars: tuple[MarketBar, ...],
    ) -> SignalBreakdown | None:
        if not bars:
            return None
        score = (bars[-1].close - Decimal("100")) / Decimal("100")
        return SignalBreakdown(
            symbol=symbol,
            score=score,
            trend=score,
            short_momentum=score,
            medium_momentum=score,
            mean_reversion=Decimal("0"),
            breakout=Decimal("0"),
            volume_confirmation=Decimal("0"),
            volatility_penalty=Decimal("0"),
        )


class StubShockStrategy(StubConfirmedStrategy):
    def _detect_regime(self, context: StrategyContext) -> RegimeState:
        return RegimeState.SHOCK


def _bars(*scores: Decimal) -> tuple[MarketBar, ...]:
    end = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
    start = end - timedelta(hours=len(scores) - 1)
    return tuple(
        MarketBar(
            timestamp=start + timedelta(hours=index),
            open=Decimal("100") * (Decimal("1") + score),
            high=Decimal("100") * (Decimal("1") + score) + Decimal("1"),
            low=Decimal("100") * (Decimal("1") + score) - Decimal("1"),
            close=Decimal("100") * (Decimal("1") + score),
            volume=Decimal("1000000"),
        )
        for index, score in enumerate(scores)
    )


def _context(
    histories: dict[str, tuple[MarketBar, ...]],
    *,
    positions: dict[str, Position] | None = None,
) -> StrategyContext:
    as_of = max(bars[-1].timestamp for bars in histories.values())
    prices = {symbol: bars[-1].close for symbol, bars in histories.items() if symbol != "SPY"}
    holdings = positions or {}
    position_value = sum(
        (position.quantity * prices[symbol] for symbol, position in holdings.items()),
        start=Decimal("0"),
    )
    nav = Decimal("67.6725")
    return StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=nav - position_value,
            positions=holdings,
            nav=nav,
            currency="USD",
            as_of=as_of,
        ),
        reference_prices=prices,
        reference_price_timestamps={symbol: as_of for symbol in prices},
        market_state_hash="m6-test-state",
        history=histories,
        benchmark_symbol="SPY",
    )


def _config(max_positions: int = 1) -> ConfirmedPersistentConfig:
    from project_fifty.strategies.baseline import BaselineConfig

    return ConfirmedPersistentConfig(
        signal_config=BaselineConfig(max_positions=max_positions),
        entry_score=Decimal("0.25"),
        retention_score=Decimal("0.05"),
        replacement_margin=Decimal("0.10"),
        entry_confirmation_bars=2,
        exit_confirmation_bars=3,
        replacement_confirmation_bars=3,
    )


def test_entry_requires_two_consecutive_confirmed_bars() -> None:
    histories = {
        "SPY": _bars(Decimal("0.10"), Decimal("0.10")),
        "AAPL": _bars(Decimal("0.20"), Decimal("0.30")),
    }
    target = StubConfirmedStrategy(_config()).generate_target(_context(histories))

    assert target.weights == {}
    assert target.evidence["AAPL.selection"] == "ENTRY_UNCONFIRMED"


def test_entry_executes_after_two_confirmed_bars() -> None:
    histories = {
        "SPY": _bars(Decimal("0.10"), Decimal("0.10")),
        "AAPL": _bars(Decimal("0.26"), Decimal("0.30")),
    }
    target = StubConfirmedStrategy(_config()).generate_target(_context(histories))

    assert set(target.weights) == {"AAPL"}
    assert target.strategy_version == "3.0.0"
    assert target.evidence["AAPL.selection"] == "ENTRY_CONFIRMED"


def test_routine_exit_waits_for_three_consecutive_bars() -> None:
    aapl = _bars(Decimal("0.10"), Decimal("0.04"), Decimal("0.03"))
    price = aapl[-1].close
    position = Position(
        symbol="AAPL",
        quantity=Decimal("20") / price,
        average_price=price,
    )
    histories = {
        "SPY": _bars(Decimal("0.10"), Decimal("0.10"), Decimal("0.10")),
        "AAPL": aapl,
    }
    target = StubConfirmedStrategy(_config()).generate_target(
        _context(histories, positions={"AAPL": position})
    )

    assert set(target.weights) == {"AAPL"}
    assert target.evidence["AAPL.selection"] == "EXIT_UNCONFIRMED"


def test_routine_exit_occurs_after_three_consecutive_bars() -> None:
    aapl = _bars(Decimal("0.04"), Decimal("0.03"), Decimal("0.02"))
    price = aapl[-1].close
    position = Position(
        symbol="AAPL",
        quantity=Decimal("20") / price,
        average_price=price,
    )
    histories = {
        "SPY": _bars(Decimal("0.10"), Decimal("0.10"), Decimal("0.10")),
        "AAPL": aapl,
    }
    target = StubConfirmedStrategy(_config()).generate_target(
        _context(histories, positions={"AAPL": position})
    )

    assert target.weights == {}
    assert target.evidence["AAPL.selection"] == "EXIT_CONFIRMED"


def test_replacement_requires_three_consecutive_margin_bars() -> None:
    aapl = _bars(Decimal("0.20"), Decimal("0.20"), Decimal("0.20"))
    msft = _bars(Decimal("0.25"), Decimal("0.35"), Decimal("0.35"))
    price = aapl[-1].close
    position = Position(
        symbol="AAPL",
        quantity=Decimal("20") / price,
        average_price=price,
    )
    histories = {
        "SPY": _bars(Decimal("0.10"), Decimal("0.10"), Decimal("0.10")),
        "AAPL": aapl,
        "MSFT": msft,
    }
    target = StubConfirmedStrategy(_config()).generate_target(
        _context(histories, positions={"AAPL": position})
    )

    assert set(target.weights) == {"AAPL"}
    assert target.evidence["MSFT.selection"] == "REPLACEMENT_UNCONFIRMED"


def test_replacement_occurs_after_three_consecutive_margin_bars() -> None:
    aapl = _bars(Decimal("0.20"), Decimal("0.20"), Decimal("0.20"))
    msft = _bars(Decimal("0.31"), Decimal("0.32"), Decimal("0.35"))
    price = aapl[-1].close
    position = Position(
        symbol="AAPL",
        quantity=Decimal("20") / price,
        average_price=price,
    )
    histories = {
        "SPY": _bars(Decimal("0.10"), Decimal("0.10"), Decimal("0.10")),
        "AAPL": aapl,
        "MSFT": msft,
    }
    target = StubConfirmedStrategy(_config()).generate_target(
        _context(histories, positions={"AAPL": position})
    )

    assert set(target.weights) == {"MSFT"}
    assert target.evidence["MSFT.selection"] == "REPLACEMENT_CONFIRMED=AAPL"


def test_shock_exit_bypasses_confirmation() -> None:
    aapl = _bars(Decimal("0.30"), Decimal("0.30"), Decimal("0.30"))
    price = aapl[-1].close
    position = Position(
        symbol="AAPL",
        quantity=Decimal("20") / price,
        average_price=price,
    )
    histories = {
        "SPY": _bars(Decimal("0.10"), Decimal("0.10"), Decimal("0.10")),
        "AAPL": aapl,
    }
    target = StubShockStrategy(_config()).generate_target(
        _context(histories, positions={"AAPL": position})
    )

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")
    assert target.evidence["selection"] == "SHOCK_EXIT"
