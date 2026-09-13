from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from project_fifty.domain.models import PortfolioState, Position, TradeAction
from project_fifty.strategies.baseline import RegimeAwareTechnicalStrategy, RegimeState
from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio
from project_fifty.strategies.proposal_builder import ProposalBuilder


def _bars(
    *,
    as_of: datetime,
    count: int = 70,
    start: Decimal = Decimal("100"),
    growth: Decimal = Decimal("0.002"),
    final_multiplier: Decimal | None = None,
    volume: Decimal = Decimal("1000000"),
) -> tuple[MarketBar, ...]:
    closes: list[Decimal] = []
    value = start
    for _ in range(count):
        closes.append(value)
        value *= Decimal("1") + growth
    if final_multiplier is not None:
        closes[-1] = closes[-2] * final_multiplier

    start_time = as_of - timedelta(minutes=5 * (count - 1))
    result: list[MarketBar] = []
    for index, close in enumerate(closes):
        result.append(
            MarketBar(
                timestamp=start_time + timedelta(minutes=5 * index),
                open=close,
                high=close * Decimal("1.002"),
                low=close * Decimal("0.998"),
                close=close,
                volume=volume,
            )
        )
    return tuple(result)


def _context(
    *,
    candidate_histories: dict[str, tuple[MarketBar, ...]],
    benchmark: tuple[MarketBar, ...],
    positions: dict[str, Position] | None = None,
    cash: Decimal = Decimal("67.6725"),
    nav: Decimal = Decimal("67.6725"),
) -> StrategyContext:
    as_of = benchmark[-1].timestamp
    prices = {symbol: bars[-1].close for symbol, bars in candidate_histories.items()}
    history = {"SPY": benchmark, **candidate_histories}
    return StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=cash,
            positions=positions or {},
            nav=nav,
            currency="USD",
            as_of=as_of,
        ),
        reference_prices=prices,
        reference_price_timestamps={symbol: as_of for symbol in prices},
        market_state_hash="market-state-1",
        history=history,
        benchmark_symbol="SPY",
    )


def test_risk_on_strategy_selects_stronger_candidate() -> None:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    context = _context(
        candidate_histories={
            "AAPL": _bars(as_of=as_of, growth=Decimal("0.005")),
            "MSFT": _bars(as_of=as_of, growth=Decimal("-0.001")),
        },
        benchmark=_bars(as_of=as_of, growth=Decimal("0.002")),
    )

    target = RegimeAwareTechnicalStrategy().generate_target(context)

    assert target.evidence["regime"] == RegimeState.RISK_ON.value
    assert "AAPL" in target.weights
    assert target.weights.get("AAPL", Decimal("0")) > target.weights.get(
        "MSFT", Decimal("0")
    )
    assert target.cash_weight == Decimal("0.30")
    assert sum(target.weights.values(), start=target.cash_weight) == Decimal("1")
    assert all(weight >= 0 for weight in target.weights.values())


def test_shock_regime_moves_strategy_target_to_cash() -> None:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    context = _context(
        candidate_histories={"AAPL": _bars(as_of=as_of, growth=Decimal("0.005"))},
        benchmark=_bars(
            as_of=as_of,
            growth=Decimal("0.002"),
            final_multiplier=Decimal("0.90"),
        ),
    )

    target = RegimeAwareTechnicalStrategy().generate_target(context)

    assert target.evidence["regime"] == RegimeState.SHOCK.value
    assert target.weights == {}
    assert target.cash_weight == Decimal("1")


def test_insufficient_candidate_history_abstains_to_cash() -> None:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    context = _context(
        candidate_histories={"AAPL": _bars(as_of=as_of, count=10)},
        benchmark=_bars(as_of=as_of),
    )

    target = RegimeAwareTechnicalStrategy().generate_target(context)

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")
    assert target.evidence["AAPL.status"] == "insufficient_history"


def test_same_point_in_time_input_is_deterministic() -> None:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    context = _context(
        candidate_histories={"AAPL": _bars(as_of=as_of, growth=Decimal("0.004"))},
        benchmark=_bars(as_of=as_of, growth=Decimal("0.002")),
    )
    strategy = RegimeAwareTechnicalStrategy()

    first = strategy.generate_target(context)
    second = strategy.generate_target(context)

    assert first == second


def test_strategy_context_rejects_future_bar() -> None:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    future = MarketBar(
        timestamp=as_of + timedelta(minutes=5),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1000"),
    )

    with pytest.raises(ValidationError, match="future bar"):
        StrategyContext(
            as_of=as_of,
            currency="USD",
            portfolio=PortfolioState(
                cash=Decimal("67.6725"),
                positions={},
                nav=Decimal("67.6725"),
                currency="USD",
                as_of=as_of,
            ),
            reference_prices={"AAPL": Decimal("100")},
            reference_price_timestamps={"AAPL": as_of},
            market_state_hash="market-state-1",
            history={"AAPL": (future,)},
        )


def test_exit_slippage_uses_actual_position_notional() -> None:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    context = StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=Decimal("27.6725"),
            positions={
                "AAPL": Position(
                    symbol="AAPL",
                    quantity=Decimal("0.4"),
                    average_price=Decimal("100"),
                )
            },
            nav=Decimal("67.6725"),
            currency="USD",
            as_of=as_of,
        ),
        reference_prices={"AAPL": Decimal("100")},
        reference_price_timestamps={"AAPL": as_of},
        market_state_hash="market-state-1",
    )
    target = TargetPortfolio(
        as_of=as_of,
        currency="USD",
        weights={},
        cash_weight=Decimal("1"),
        strategy_id="test",
        strategy_version="1",
        confidence=Decimal("1"),
        market_state_hash="market-state-1",
    )

    proposals = ProposalBuilder(
        min_order_notional=Decimal("1"),
        estimated_slippage_rate=Decimal("0.01"),
    ).build(target=target, context=context)

    assert len(proposals) == 1
    assert proposals[0].action == TradeAction.EXIT
    assert proposals[0].estimated_slippage == Decimal("0.4")
