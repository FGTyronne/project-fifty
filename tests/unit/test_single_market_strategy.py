from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.domain.models import PortfolioState, Position
from project_fifty.strategies.contracts import MarketBar, StrategyContext
from project_fifty.strategies.m9 import m9_rebalance_policy
from project_fifty.strategies.single_market import (
    SingleMarketTrendConfig,
    SingleMarketTrendStrategy,
)


def _bars(*, count: int, growth: Decimal) -> tuple[MarketBar, ...]:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    first = as_of - timedelta(days=count - 1)
    price = Decimal("100")
    bars: list[MarketBar] = []
    for index in range(count):
        bars.append(
            MarketBar(
                timestamp=first + timedelta(days=index),
                open=price,
                high=price * Decimal("1.002"),
                low=price * Decimal("0.998"),
                close=price,
                volume=Decimal("1000000"),
            )
        )
        price *= Decimal("1") + growth
    return tuple(bars)


def _context(
    *,
    count: int = 210,
    growth: Decimal = Decimal("0.001"),
    invested_value: Decimal | None = None,
) -> StrategyContext:
    spy = _bars(count=count, growth=growth)
    price = spy[-1].close
    as_of = spy[-1].timestamp
    positions: dict[str, Position] = {}
    cash = Decimal("67.6725")
    if invested_value is not None:
        positions["SPY"] = Position(
            symbol="SPY",
            quantity=invested_value / price,
            average_price=price,
        )
        cash -= invested_value
    return StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=cash,
            positions=positions,
            nav=Decimal("67.6725"),
            currency="USD",
            as_of=as_of,
        ),
        reference_prices={"SPY": price},
        reference_price_timestamps={"SPY": as_of},
        market_state_hash="m9-test-state",
        history={"SPY": spy},
        benchmark_symbol="SPY",
    )


def test_m9_parameters_are_frozen() -> None:
    config = SingleMarketTrendConfig()

    assert config.symbol == "SPY"
    assert config.rebalance_every_bars == 21
    assert config.trend_sma_days == 200
    assert config.momentum_days == 126


def test_non_scheduled_bar_preserves_spy_position_and_creates_no_rebalance() -> None:
    context = _context(count=211, invested_value=Decimal("55"))
    target = SingleMarketTrendStrategy().generate_target(context)

    expected_weight = Decimal("55") / Decimal("67.6725")
    assert target.strategy_version == "6.0.0"
    assert target.weights == {"SPY": expected_weight}
    assert target.cash_weight == Decimal("1") - expected_weight
    assert target.evidence["selection"] == "NOT_SCHEDULED"

    plan = m9_rebalance_policy().plan(target=target, context=context)
    assert plan.executable_symbols == frozenset()


def test_scheduled_risk_on_from_cash_targets_full_spy() -> None:
    target = SingleMarketTrendStrategy().generate_target(_context())

    assert target.weights == {"SPY": Decimal("1")}
    assert target.cash_weight == Decimal("0")
    assert target.evidence["selection"] == "ENTER_RISK_ON"
    assert target.evidence["raw_risk_state"] == "RISK_ON"


def test_scheduled_persistent_risk_on_preserves_drifted_weight() -> None:
    context = _context(invested_value=Decimal("55"))
    target = SingleMarketTrendStrategy().generate_target(context)

    expected_weight = Decimal("55") / Decimal("67.6725")
    assert target.weights == {"SPY": expected_weight}
    assert target.cash_weight == Decimal("1") - expected_weight
    assert target.evidence["selection"] == "HOLD_RISK_ON"

    plan = m9_rebalance_policy().plan(target=target, context=context)
    assert plan.executable_symbols == frozenset()


def test_scheduled_risk_off_exits_spy_to_cash() -> None:
    context = _context(growth=Decimal("-0.001"), invested_value=Decimal("55"))
    target = SingleMarketTrendStrategy().generate_target(context)

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")
    assert target.evidence["selection"] == "EXIT_TO_CASH"
    assert target.evidence["raw_risk_state"] == "RISK_OFF"

    plan = m9_rebalance_policy().plan(target=target, context=context)
    assert plan.executable_symbols == frozenset({"SPY"})


def test_m9_retains_m8_economic_filter() -> None:
    policy = m9_rebalance_policy()

    assert policy.config.minimum_trade_notional == Decimal("5.00")
    assert policy.config.minimum_trade_fraction_of_nav == Decimal("0.15")
    assert policy.config.force_full_exits is True
