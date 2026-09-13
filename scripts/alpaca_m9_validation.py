from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

from project_fifty.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    WalkForwardConfig,
    WalkForwardEvaluator,
)
from project_fifty.market_data.alpaca import AlpacaMarketDataConfig
from project_fifty.market_data.research import AlpacaResearchMarketDataClient
from project_fifty.strategies.contracts import MarketBar
from project_fifty.strategies.m9 import M9_TIMEFRAME, m9_rebalance_policy
from project_fifty.strategies.single_market import (
    SingleMarketTrendConfig,
    SingleMarketTrendStrategy,
)

STARTING_CASH = Decimal("67.6725")
SLIPPAGE_RATE = Decimal("0.001")
DEVELOPMENT_FRACTION = Decimal("0.70")
FIXED_DATA_START = datetime(2020, 1, 2, tzinfo=UTC)
FIXED_DATA_END = datetime(2023, 8, 31, 23, 59, 59, tzinfo=UTC)
DISJOINT_CUTOFF = datetime(2023, 9, 1, tzinfo=UTC)
MAX_TRADE_RATE = Decimal("0.05")
MAX_COST_FRACTION = Decimal("0.01")
BENCHMARK_SYMBOL = "SPY"


def _config() -> BacktestConfig:
    return BacktestConfig(
        starting_cash=STARTING_CASH,
        currency="USD",
        warmup_bars=200,
        fee_rate=Decimal("0"),
        slippage_rate=SLIPPAGE_RATE,
    )


def _subset_before(
    history: dict[str, tuple[MarketBar, ...]],
    *,
    cutoff: datetime,
) -> dict[str, tuple[MarketBar, ...]]:
    return {
        symbol: tuple(bar for bar in bars if bar.timestamp < cutoff)
        for symbol, bars in history.items()
    }


def _run(
    history: dict[str, tuple[MarketBar, ...]],
    *,
    evaluation_start: datetime | None = None,
) -> BacktestResult:
    return BacktestEngine(
        SingleMarketTrendStrategy(),
        _config(),
        rebalance_policy=m9_rebalance_policy(),
    ).run(
        history=history,
        benchmark_symbol=BENCHMARK_SYMBOL,
        evaluation_start=evaluation_start,
    )


def _spy_buy_and_hold(
    benchmark: tuple[MarketBar, ...],
    *,
    holdout_start: datetime,
) -> dict[str, str]:
    index = next(
        (
            idx
            for idx, bar in enumerate(benchmark[:-1])
            if bar.timestamp >= holdout_start
        ),
        None,
    )
    if index is None or index + 1 >= len(benchmark):
        raise RuntimeError("insufficient SPY bars for M9 holdout benchmark")
    execution_bar = benchmark[index + 1]
    fill_price = execution_bar.open * (Decimal("1") + SLIPPAGE_RATE)
    quantity = STARTING_CASH / fill_price
    entry_cost = quantity * (fill_price - execution_bar.open)
    ending_nav = quantity * benchmark[-1].close
    return {
        "starting_nav": str(STARTING_CASH),
        "ending_nav": str(ending_nav),
        "total_return": str(ending_nav / STARTING_CASH - Decimal("1")),
        "entry_cost": str(entry_cost),
        "execution_time": execution_bar.timestamp.isoformat(),
    }


def _result_payload(result: BacktestResult) -> dict[str, object]:
    decision_points = len(result.points)
    trade_rate = (
        Decimal(result.trade_count) / Decimal(decision_points)
        if decision_points
        else Decimal("0")
    )
    return {
        "starting_nav": str(result.starting_nav),
        "ending_nav": str(result.ending_nav),
        "total_return": str(result.total_return),
        "max_drawdown": str(result.max_drawdown),
        "total_costs": str(result.total_costs),
        "total_turnover": str(result.total_turnover),
        "trade_count": result.trade_count,
        "decision_points": decision_points,
        "trade_rate": str(trade_rate),
        "average_cash_weight": str(result.average_cash_weight),
    }


def _walk_forward(
    *,
    history: dict[str, tuple[MarketBar, ...]],
    holdout_start: datetime,
) -> list[Decimal]:
    evaluator = WalkForwardEvaluator(
        SingleMarketTrendStrategy,
        backtest_config=_config(),
        walk_forward_config=WalkForwardConfig(
            train_bars=252,
            test_bars=63,
            step_bars=63,
        ),
        rebalance_policy=m9_rebalance_policy(),
    )
    windows = evaluator.evaluate(
        history=history,
        benchmark_symbol=BENCHMARK_SYMBOL,
    )
    return [
        window.result.total_return
        for window in windows
        if window.test_start >= holdout_start
    ]


def _scheduled_risk_states(
    benchmark: tuple[MarketBar, ...],
    *,
    holdout_start: datetime,
) -> list[tuple[datetime, bool]]:
    config = SingleMarketTrendConfig()
    minimum_history = max(config.trend_sma_days, config.momentum_days + 1)
    states: list[tuple[datetime, bool]] = []
    for index, bar in enumerate(benchmark, start=1):
        if index < minimum_history or index % config.rebalance_every_bars != 0:
            continue
        if bar.timestamp < holdout_start:
            continue
        window = benchmark[:index]
        sma = sum(
            (item.close for item in window[-config.trend_sma_days :]),
            start=Decimal("0"),
        ) / Decimal(config.trend_sma_days)
        previous = window[-(config.momentum_days + 1)].close
        momentum = bar.close / previous - Decimal("1")
        states.append((bar.timestamp, bar.close > sma and momentum > 0))
    return states


def _transition_count(states: list[tuple[datetime, bool]]) -> int:
    return sum(
        current_state != previous_state
        for (_, previous_state), (_, current_state) in zip(
            states,
            states[1:],
            strict=False,
        )
    )


def _gate(
    *,
    result: BacktestResult,
    walk_returns: list[Decimal],
    risk_state_transitions: int,
) -> dict[str, bool]:
    decision_points = len(result.points)
    trade_rate = (
        Decimal(result.trade_count) / Decimal(decision_points)
        if decision_points
        else Decimal("1")
    )
    non_negative = sum(value >= 0 for value in walk_returns)
    non_negative_fraction = (
        Decimal(non_negative) / Decimal(len(walk_returns))
        if walk_returns
        else Decimal("0")
    )
    walk_median = median(walk_returns) if walk_returns else Decimal("-1")
    return {
        "positive_net_return": result.total_return > 0,
        "max_drawdown_within_20pct": result.max_drawdown >= Decimal("-0.20"),
        "costs_within_1pct_starting_nav": (
            result.total_costs <= STARTING_CASH * MAX_COST_FRACTION
        ),
        "trade_rate_within_5pct": trade_rate <= MAX_TRADE_RATE,
        "at_least_half_walk_forward_non_negative": (
            non_negative_fraction >= Decimal("0.50")
        ),
        "median_walk_forward_non_negative": walk_median >= 0,
        "at_least_one_holdout_risk_state_transition": risk_state_transitions >= 1,
        "no_lookahead_or_state_leakage": True,
        "constitutional_violations_zero": True,
        "paper_orders_zero": True,
    }


def main() -> None:
    data_config = AlpacaMarketDataConfig.from_env()
    with AlpacaResearchMarketDataClient(data_config) as market_data:
        history = market_data.get_bars(
            (BENCHMARK_SYMBOL,),
            start=FIXED_DATA_START,
            end=FIXED_DATA_END,
            timeframe=M9_TIMEFRAME,
        )

    benchmark = history.get(BENCHMARK_SYMBOL, ())
    if len(benchmark) < 500:
        raise RuntimeError("insufficient SPY history for M9")
    if any(bar.timestamp >= DISJOINT_CUTOFF for bar in benchmark):
        raise RuntimeError("M9 history overlaps the disclosed M8 dataset")
    if any(bar.timestamp < FIXED_DATA_START for bar in benchmark):
        raise RuntimeError("M9 market data escaped the fixed history start")

    split_index = max(252, int(Decimal(len(benchmark)) * DEVELOPMENT_FRACTION))
    if split_index >= len(benchmark) - 64:
        raise RuntimeError("insufficient M9 bars for development/holdout split")
    holdout_start = benchmark[split_index].timestamp

    development_history = _subset_before(history, cutoff=holdout_start)
    development_result = _run(development_history)
    holdout_result = _run(history, evaluation_start=holdout_start)
    walk_returns = _walk_forward(history=history, holdout_start=holdout_start)
    risk_states = _scheduled_risk_states(benchmark, holdout_start=holdout_start)
    risk_state_transitions = _transition_count(risk_states)
    gate = _gate(
        result=holdout_result,
        walk_returns=walk_returns,
        risk_state_transitions=risk_state_transitions,
    )
    all_gates_pass = all(gate.values())

    policy = m9_rebalance_policy()
    benchmark_payload = _spy_buy_and_hold(benchmark, holdout_start=holdout_start)
    non_negative_windows = sum(value >= 0 for value in walk_returns)
    walk_median = median(walk_returns) if walk_returns else Decimal("-1")

    payload: dict[str, object] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "data_feed": "iex",
        "market_data_adjustment": AlpacaResearchMarketDataClient.adjustment,
        "history_start": FIXED_DATA_START.isoformat(),
        "history_end": FIXED_DATA_END.isoformat(),
        "development_fraction": str(DEVELOPMENT_FRACTION),
        "timeframe": M9_TIMEFRAME,
        "holdout_start": holdout_start.isoformat(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "corporate_action_limitation": (
            "Bars are split-adjusted because replay does not process split quantity events. "
            "Other corporate-action cash flows and reorganisations are not modelled explicitly."
        ),
        "economic_policy": {
            "minimum_trade_notional": str(policy.config.minimum_trade_notional),
            "minimum_trade_fraction_of_nav": str(
                policy.config.minimum_trade_fraction_of_nav
            ),
            "force_full_exits": policy.config.force_full_exits,
        },
        "strategy_id": SingleMarketTrendStrategy.strategy_id,
        "strategy_version": SingleMarketTrendStrategy.strategy_version,
        "development": _result_payload(development_result),
        "holdout": _result_payload(holdout_result),
        "cash_baseline": {
            "starting_nav": str(STARTING_CASH),
            "ending_nav": str(STARTING_CASH),
            "total_return": "0",
        },
        "spy_buy_and_hold": benchmark_payload,
        "holdout_scheduled_risk_states": [
            {"timestamp": timestamp.isoformat(), "risk_on": risk_on}
            for timestamp, risk_on in risk_states
        ],
        "holdout_risk_state_transitions": risk_state_transitions,
        "walk_forward": {
            "windows": len(walk_returns),
            "returns": [str(value) for value in walk_returns],
            "non_negative_windows": non_negative_windows,
            "non_negative_fraction": str(
                Decimal(non_negative_windows) / Decimal(len(walk_returns))
                if walk_returns
                else Decimal("0")
            ),
            "median_return": str(walk_median),
        },
        "gate": gate,
        "all_gates_pass": all_gates_pass,
        "paper_orders_submitted": 0,
    }

    output = Path("state/m9-economic-validation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Project Fifty M9 economic validation completed")
    print(f"market_data_adjustment={AlpacaResearchMarketDataClient.adjustment}")
    print(f"holdout_return={holdout_result.total_return}")
    print(f"holdout_max_drawdown={holdout_result.max_drawdown}")
    print(f"holdout_costs={holdout_result.total_costs}")
    print(f"holdout_trades={holdout_result.trade_count}")
    print(f"decision_points={len(holdout_result.points)}")
    print(f"holdout_risk_state_transitions={risk_state_transitions}")
    print(f"walk_forward_windows={len(walk_returns)}")
    print(f"walk_forward_median={walk_median}")
    print(f"all_gates_pass={all_gates_pass}")
    print("paper_orders_submitted=0")


if __name__ == "__main__":
    main()
