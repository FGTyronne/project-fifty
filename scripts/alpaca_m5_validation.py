from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
from project_fifty.brokers.alpaca.broker import AlpacaPaperBroker
from project_fifty.brokers.alpaca.config import AlpacaPaperConfig
from project_fifty.market_data.alpaca import AlpacaMarketDataClient, AlpacaMarketDataConfig
from project_fifty.market_data.universe import AlpacaUniverseBuilder, CandidateUniverse
from project_fifty.strategies.contracts import MarketBar
from project_fifty.strategies.persistent import PersistentRegimeTechnicalStrategy
from project_fifty.strategies.rebalance import EconomicRebalancePolicy

STARTING_CASH = Decimal("67.6725")
SLIPPAGE_RATE = Decimal("0.001")
HISTORY_DAYS = 240
DEVELOPMENT_FRACTION = Decimal("0.70")
TIMEFRAMES: tuple[str, ...] = ("30Min", "1Hour")
M4_TRADE_RATE = Decimal(2132) / Decimal(2499)
MAX_M5_TRADE_RATE = M4_TRADE_RATE / Decimal("4")


def _config() -> BacktestConfig:
    return BacktestConfig(
        starting_cash=STARTING_CASH,
        currency="USD",
        warmup_bars=60,
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
    universe: CandidateUniverse,
    *,
    evaluation_start: datetime | None = None,
) -> BacktestResult:
    return BacktestEngine(
        PersistentRegimeTechnicalStrategy(),
        _config(),
        rebalance_policy=EconomicRebalancePolicy(),
    ).run(
        history=history,
        benchmark_symbol=universe.benchmark_symbol,
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
        raise RuntimeError("insufficient SPY bars for holdout benchmark")
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
    universe: CandidateUniverse,
    holdout_start: datetime,
) -> list[Decimal]:
    benchmark_count = len(history[universe.benchmark_symbol])
    train_bars = min(350, max(120, benchmark_count // 5))
    test_bars = min(70, max(35, benchmark_count // 20))
    evaluator = WalkForwardEvaluator(
        PersistentRegimeTechnicalStrategy,
        backtest_config=_config(),
        walk_forward_config=WalkForwardConfig(
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=test_bars,
        ),
        rebalance_policy=EconomicRebalancePolicy(),
    )
    windows = evaluator.evaluate(
        history=history,
        benchmark_symbol=universe.benchmark_symbol,
    )
    return [
        window.result.total_return
        for window in windows
        if window.test_start >= holdout_start
    ]


def _gate(
    *,
    result: BacktestResult,
    walk_returns: list[Decimal],
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
    median_return = median(walk_returns) if walk_returns else Decimal("-1")
    return {
        "positive_net_return": result.total_return > 0,
        "max_drawdown_within_20pct": result.max_drawdown >= Decimal("-0.20"),
        "costs_within_5pct_starting_nav": (
            result.total_costs <= STARTING_CASH * Decimal("0.05")
        ),
        "trade_rate_at_least_75pct_lower_than_m4": trade_rate <= MAX_M5_TRADE_RATE,
        "at_least_half_walk_forward_non_negative": (
            non_negative_fraction >= Decimal("0.50")
        ),
        "median_walk_forward_non_negative": median_return >= 0,
        "paper_orders_zero": True,
    }


def main() -> None:
    paper_config = AlpacaPaperConfig.from_env()
    data_config = AlpacaMarketDataConfig.from_env()

    with AlpacaPaperBroker(paper_config) as broker:
        universe = AlpacaUniverseBuilder(broker).build()

    end = datetime.now(UTC) - timedelta(minutes=90)
    start = end - timedelta(days=HISTORY_DAYS)
    policy = EconomicRebalancePolicy()

    histories: dict[str, dict[str, tuple[MarketBar, ...]]] = {}
    development_results: dict[str, BacktestResult] = {}
    holdout_starts: dict[str, datetime] = {}

    with AlpacaMarketDataClient(data_config) as market_data:
        for timeframe in TIMEFRAMES:
            history = market_data.get_bars(
                universe.all_symbols,
                start=start,
                end=end,
                timeframe=timeframe,
            )
            minimum = 180
            missing = [
                symbol
                for symbol in universe.all_symbols
                if len(history.get(symbol, ())) < minimum
            ]
            if missing:
                raise RuntimeError(
                    f"insufficient {timeframe} history for: {','.join(missing)}"
                )
            histories[timeframe] = history
            benchmark = history[universe.benchmark_symbol]
            split_index = max(61, int(Decimal(len(benchmark)) * DEVELOPMENT_FRACTION))
            if split_index >= len(benchmark) - 2:
                raise RuntimeError(f"insufficient {timeframe} bars for holdout split")
            holdout_start = benchmark[split_index].timestamp
            holdout_starts[timeframe] = holdout_start
            development_history = _subset_before(history, cutoff=holdout_start)
            development_results[timeframe] = BacktestEngine(
                PersistentRegimeTechnicalStrategy(),
                _config(),
                rebalance_policy=policy,
            ).run(
                history=development_history,
                benchmark_symbol=universe.benchmark_symbol,
            )

    # Cadence is selected using development data only. The holdout is not consulted here.
    selected_timeframe = max(
        TIMEFRAMES,
        key=lambda timeframe: (
            development_results[timeframe].total_return,
            -development_results[timeframe].total_costs,
            -Decimal(development_results[timeframe].trade_count),
        ),
    )
    history = histories[selected_timeframe]
    holdout_start = holdout_starts[selected_timeframe]
    holdout_result = _run(
        history,
        universe,
        evaluation_start=holdout_start,
    )
    walk_returns = _walk_forward(
        history=history,
        universe=universe,
        holdout_start=holdout_start,
    )
    gate = _gate(result=holdout_result, walk_returns=walk_returns)
    all_gates_pass = all(gate.values())

    benchmark_payload = _spy_buy_and_hold(
        history[universe.benchmark_symbol],
        holdout_start=holdout_start,
    )
    non_negative_windows = sum(value >= 0 for value in walk_returns)
    walk_median = median(walk_returns) if walk_returns else Decimal("-1")

    payload: dict[str, object] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "data_feed": "iex",
        "history_start": start.isoformat(),
        "history_end": end.isoformat(),
        "history_days": HISTORY_DAYS,
        "development_fraction": str(DEVELOPMENT_FRACTION),
        "timeframe_candidates": list(TIMEFRAMES),
        "selected_timeframe": selected_timeframe,
        "holdout_start": holdout_start.isoformat(),
        "candidate_symbols": list(universe.symbols),
        "benchmark_symbol": universe.benchmark_symbol,
        "economic_policy": {
            "minimum_trade_notional": str(policy.config.minimum_trade_notional),
            "minimum_trade_fraction_of_nav": str(
                policy.config.minimum_trade_fraction_of_nav
            ),
            "force_full_exits": policy.config.force_full_exits,
        },
        "strategy_id": PersistentRegimeTechnicalStrategy.strategy_id,
        "strategy_version": PersistentRegimeTechnicalStrategy.strategy_version,
        "development": {
            timeframe: _result_payload(result)
            for timeframe, result in development_results.items()
        },
        "holdout": _result_payload(holdout_result),
        "cash_baseline": {
            "starting_nav": str(STARTING_CASH),
            "ending_nav": str(STARTING_CASH),
            "total_return": "0",
        },
        "spy_buy_and_hold": benchmark_payload,
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

    output = Path("state/m5-economic-validation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Project Fifty M5 economic validation completed")
    print(f"selected_timeframe={selected_timeframe}")
    print(f"holdout_return={holdout_result.total_return}")
    print(f"holdout_max_drawdown={holdout_result.max_drawdown}")
    print(f"holdout_costs={holdout_result.total_costs}")
    print(f"holdout_trades={holdout_result.trade_count}")
    print(f"walk_forward_windows={len(walk_returns)}")
    print(f"walk_forward_median={walk_median}")
    print(f"all_gates_pass={all_gates_pass}")
    print("paper_orders_submitted=0")


if __name__ == "__main__":
    main()
