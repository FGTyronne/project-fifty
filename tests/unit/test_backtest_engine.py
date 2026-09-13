from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    WalkForwardConfig,
    WalkForwardEvaluator,
)
from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio


class HalfAaplStrategy:
    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={"AAPL": Decimal("0.5")},
            cash_weight=Decimal("0.5"),
            strategy_id="half-aapl",
            strategy_version="1",
            confidence=Decimal("1"),
            market_state_hash=context.market_state_hash,
        )


def _bar(timestamp: datetime, open_price: str, close_price: str) -> MarketBar:
    open_value = Decimal(open_price)
    close_value = Decimal(close_price)
    high = max(open_value, close_value)
    low = min(open_value, close_value)
    return MarketBar(
        timestamp=timestamp,
        open=open_value,
        high=high,
        low=low,
        close=close_value,
        volume=Decimal("1000"),
    )


def _history(count: int = 12) -> dict[str, tuple[MarketBar, ...]]:
    start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    spy: list[MarketBar] = []
    aapl: list[MarketBar] = []
    for index in range(count):
        timestamp = start + timedelta(days=index)
        spy.append(_bar(timestamp, "500", "500"))
        if index < 3:
            aapl.append(_bar(timestamp, "100", "100"))
        else:
            aapl.append(_bar(timestamp, "200", "200"))
    return {"AAPL": tuple(aapl), "SPY": tuple(spy)}


def test_backtest_decides_on_close_and_executes_at_next_bar_open() -> None:
    result = BacktestEngine(
        HalfAaplStrategy(),
        BacktestConfig(
            starting_cash=Decimal("100"),
            warmup_bars=3,
            slippage_rate=Decimal("0"),
        ),
    ).run(history=_history(), benchmark_symbol="SPY")

    assert result.points
    first = result.points[0]
    # Day-three decision sees AAPL at 100, but day-four execution occurs at the 200 open.
    assert first.positions["AAPL"] == Decimal("0.25")
    assert first.nav == Decimal("100")
    assert result.trade_count >= 1


def test_slippage_is_counted_as_cost() -> None:
    result = BacktestEngine(
        HalfAaplStrategy(),
        BacktestConfig(
            starting_cash=Decimal("100"),
            warmup_bars=3,
            slippage_rate=Decimal("0.01"),
        ),
    ).run(history=_history(), benchmark_symbol="SPY")

    assert result.total_costs > 0
    assert result.ending_nav < Decimal("100")


def test_walk_forward_creates_isolated_test_windows() -> None:
    evaluator = WalkForwardEvaluator(
        HalfAaplStrategy,
        backtest_config=BacktestConfig(
            starting_cash=Decimal("100"),
            warmup_bars=3,
            slippage_rate=Decimal("0"),
        ),
        walk_forward_config=WalkForwardConfig(train_bars=4, test_bars=3, step_bars=2),
    )

    windows = evaluator.evaluate(history=_history(14), benchmark_symbol="SPY")

    assert len(windows) >= 2
    assert all(window.test_start < window.test_end for window in windows)
    assert all(window.result.starting_nav == Decimal("100") for window in windows)
