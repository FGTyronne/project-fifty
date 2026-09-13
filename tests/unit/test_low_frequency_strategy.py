from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.domain.models import PortfolioState, Position
from project_fifty.strategies.contracts import MarketBar, StrategyContext
from project_fifty.strategies.low_frequency import LowFrequencyMomentumStrategy
from project_fifty.strategies.m8 import m8_rebalance_policy


def _bars(*, count: int, growth: Decimal, start: Decimal = Decimal("100")) -> tuple[MarketBar, ...]:
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    first = as_of - timedelta(days=count - 1)
    price = start
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
    benchmark_count: int = 105,
    spy_growth: Decimal = Decimal("0.001"),
    aapl_growth: Decimal = Decimal("0.002"),
    msft_growth: Decimal = Decimal("0.0025"),
    incumbent: str | None = None,
    incumbent_value: Decimal = Decimal("37"),
) -> StrategyContext:
    spy = _bars(count=benchmark_count, growth=spy_growth)
    aapl = _bars(count=benchmark_count, growth=aapl_growth)
    msft = _bars(count=benchmark_count, growth=msft_growth)
    as_of = spy[-1].timestamp
    prices = {"SPY": spy[-1].close, "AAPL": aapl[-1].close, "MSFT": msft[-1].close}
    positions: dict[str, Position] = {}
    cash = Decimal("67.6725")
    if incumbent is not None:
        price = prices[incumbent]
        quantity = incumbent_value / price
        positions[incumbent] = Position(
            symbol=incumbent,
            quantity=quantity,
            average_price=price,
        )
        cash -= incumbent_value
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
        reference_prices=prices,
        reference_price_timestamps={symbol: as_of for symbol in prices},
        market_state_hash="m8-test-state",
        history={"SPY": spy, "AAPL": aapl, "MSFT": msft},
        benchmark_symbol="SPY",
    )


def test_non_scheduled_bar_preserves_current_weight() -> None:
    context = _context(benchmark_count=101, incumbent="AAPL", incumbent_value=Decimal("37"))

    target = LowFrequencyMomentumStrategy().generate_target(context)

    expected_weight = Decimal("37") / Decimal("67.6725")
    assert target.strategy_version == "5.0.0"
    assert target.weights == {"AAPL": expected_weight}
    assert target.cash_weight == Decimal("1") - expected_weight
    assert target.evidence["selection"] == "NOT_SCHEDULED"


def test_non_scheduled_bar_produces_no_executable_rebalance() -> None:
    context = _context(benchmark_count=101, incumbent="AAPL", incumbent_value=Decimal("37"))
    target = LowFrequencyMomentumStrategy().generate_target(context)

    plan = m8_rebalance_policy().plan(target=target, context=context)

    assert plan.executable_symbols == frozenset()


def test_scheduled_decision_enters_best_eligible_candidate_at_seventy_percent() -> None:
    target = LowFrequencyMomentumStrategy().generate_target(_context())

    assert target.weights == {"MSFT": Decimal("0.70")}
    assert target.cash_weight == Decimal("0.30")
    assert target.evidence["selection"] == "ENTRY=MSFT"


def test_eligible_incumbent_is_held_without_mechanical_recentering() -> None:
    context = _context(incumbent="AAPL", incumbent_value=Decimal("37"))

    target = LowFrequencyMomentumStrategy().generate_target(context)

    expected_weight = Decimal("37") / Decimal("67.6725")
    assert target.weights == {"AAPL": expected_weight}
    assert target.cash_weight == Decimal("1") - expected_weight
    assert target.evidence["selection"] == "HOLD_INCUMBENT=AAPL"


def test_challenger_replaces_incumbent_only_after_five_point_momentum_edge() -> None:
    context = _context(
        incumbent="AAPL",
        incumbent_value=Decimal("37"),
        msft_growth=Decimal("0.004"),
    )

    target = LowFrequencyMomentumStrategy().generate_target(context)

    assert target.weights == {"MSFT": Decimal("0.70")}
    assert target.cash_weight == Decimal("0.30")
    assert target.evidence["selection"] == "REPLACE=AAPL->MSFT"


def test_benchmark_risk_gate_moves_portfolio_to_cash_on_scheduled_decision() -> None:
    context = _context(
        incumbent="AAPL",
        incumbent_value=Decimal("37"),
        spy_growth=Decimal("-0.001"),
    )

    target = LowFrequencyMomentumStrategy().generate_target(context)

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")
    assert target.evidence["selection"] == "BENCHMARK_RISK_GATE_OFF"


def test_m8_economic_policy_is_frozen_at_five_dollars_or_fifteen_percent() -> None:
    policy = m8_rebalance_policy()

    assert policy.config.minimum_trade_notional == Decimal("5.00")
    assert policy.config.minimum_trade_fraction_of_nav == Decimal("0.15")
    assert policy.config.force_full_exits is True
