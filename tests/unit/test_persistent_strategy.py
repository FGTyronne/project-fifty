from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.domain.models import PortfolioState, Position
from project_fifty.strategies.baseline import BaselineConfig
from project_fifty.strategies.contracts import MarketBar, StrategyContext
from project_fifty.strategies.persistent import (
    PersistentBaselineConfig,
    PersistentRegimeTechnicalStrategy,
)


def _bars(
    *,
    as_of: datetime,
    growth: Decimal,
    count: int = 70,
) -> tuple[MarketBar, ...]:
    closes: list[Decimal] = []
    value = Decimal("100")
    for _ in range(count):
        closes.append(value)
        value *= Decimal("1") + growth
    start_time = as_of - timedelta(minutes=30 * (count - 1))
    return tuple(
        MarketBar(
            timestamp=start_time + timedelta(minutes=30 * index),
            open=close,
            high=close * Decimal("1.002"),
            low=close * Decimal("0.998"),
            close=close,
            volume=Decimal("1000000"),
        )
        for index, close in enumerate(closes)
    )


def _context(
    *,
    positions: dict[str, Position] | None = None,
    aapl_growth: Decimal = Decimal("0.003"),
    msft_growth: Decimal = Decimal("0.004"),
) -> StrategyContext:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    aapl = _bars(as_of=as_of, growth=aapl_growth)
    msft = _bars(as_of=as_of, growth=msft_growth)
    spy = _bars(as_of=as_of, growth=Decimal("0.002"))
    holdings = positions or {}
    prices = {"AAPL": aapl[-1].close, "MSFT": msft[-1].close}
    position_value = sum(
        (position.quantity * prices[symbol] for symbol, position in holdings.items()),
        start=Decimal("0"),
    )
    cash = Decimal("67.6725") - position_value
    return StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=cash,
            positions=holdings,
            nav=Decimal("67.6725"),
            currency="USD",
            as_of=as_of,
        ),
        reference_prices=prices,
        reference_price_timestamps={"AAPL": as_of, "MSFT": as_of},
        market_state_hash="persistent-state",
        history={"SPY": spy, "AAPL": aapl, "MSFT": msft},
        benchmark_symbol="SPY",
    )


def test_v2_uses_stable_equal_weights_for_selected_positions() -> None:
    strategy = PersistentRegimeTechnicalStrategy(
        PersistentBaselineConfig(
            signal_config=BaselineConfig(max_positions=2),
            entry_score=Decimal("-1"),
            retention_score=Decimal("-1"),
            replacement_margin=Decimal("0.10"),
        )
    )

    target = strategy.generate_target(_context())

    assert target.strategy_version == "2.0.0"
    assert set(target.weights) == {"AAPL", "MSFT"}
    assert target.weights["AAPL"] == Decimal("0.35")
    assert target.weights["MSFT"] == Decimal("0.35")
    assert target.cash_weight == Decimal("0.30")


def test_incumbent_is_not_replaced_without_required_margin() -> None:
    context_without_position = _context()
    aapl_price = context_without_position.reference_prices["AAPL"]
    context = _context(
        positions={
            "AAPL": Position(
                symbol="AAPL",
                quantity=Decimal("20") / aapl_price,
                average_price=aapl_price,
            )
        }
    )
    strategy = PersistentRegimeTechnicalStrategy(
        PersistentBaselineConfig(
            signal_config=BaselineConfig(max_positions=1),
            entry_score=Decimal("-1"),
            retention_score=Decimal("-1"),
            replacement_margin=Decimal("2"),
        )
    )

    target = strategy.generate_target(context)

    assert set(target.weights) == {"AAPL"}
    assert target.evidence["AAPL.selection"] == "incumbent_retained"


def test_zero_budget_still_exits_immediately_to_cash() -> None:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    aapl = _bars(as_of=as_of, growth=Decimal("0.003"))
    spy = list(_bars(as_of=as_of, growth=Decimal("0.002")))
    previous = spy[-2].close
    crash_close = previous * Decimal("0.90")
    spy[-1] = MarketBar(
        timestamp=spy[-1].timestamp,
        open=crash_close,
        high=crash_close * Decimal("1.002"),
        low=crash_close * Decimal("0.998"),
        close=crash_close,
        volume=spy[-1].volume,
    )
    price = aapl[-1].close
    position = Position(
        symbol="AAPL",
        quantity=Decimal("20") / price,
        average_price=price,
    )
    context = StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=Decimal("47.6725"),
            positions={"AAPL": position},
            nav=Decimal("67.6725"),
            currency="USD",
            as_of=as_of,
        ),
        reference_prices={"AAPL": price},
        reference_price_timestamps={"AAPL": as_of},
        market_state_hash="shock-state",
        history={"SPY": tuple(spy), "AAPL": aapl},
        benchmark_symbol="SPY",
    )

    target = PersistentRegimeTechnicalStrategy().generate_target(context)

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")
    assert target.evidence["selection"] == "risk_budget_zero"
