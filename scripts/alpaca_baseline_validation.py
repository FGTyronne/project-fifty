from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from project_fifty.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    WalkForwardConfig,
    WalkForwardEvaluator,
)
from project_fifty.brokers.alpaca.broker import AlpacaPaperBroker
from project_fifty.brokers.alpaca.config import AlpacaPaperConfig
from project_fifty.market_data.alpaca import AlpacaMarketDataClient, AlpacaMarketDataConfig
from project_fifty.market_data.universe import AlpacaUniverseBuilder
from project_fifty.strategies.baseline import RegimeAwareTechnicalStrategy


def main() -> None:
    paper_config = AlpacaPaperConfig.from_env()
    data_config = AlpacaMarketDataConfig.from_env()

    with AlpacaPaperBroker(paper_config) as broker:
        universe = AlpacaUniverseBuilder(broker).build()

    end = datetime.now(UTC) - timedelta(minutes=20)
    start = end - timedelta(days=45)
    with AlpacaMarketDataClient(data_config) as market_data:
        history = market_data.get_bars(
            universe.all_symbols,
            start=start,
            end=end,
            timeframe="5Min",
        )

    missing = [symbol for symbol in universe.all_symbols if len(history.get(symbol, ())) < 61]
    if missing:
        raise RuntimeError(f"insufficient 5Min history for: {','.join(missing)}")

    config = BacktestConfig(
        starting_cash=Decimal("67.6725"),
        currency="USD",
        warmup_bars=60,
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0.001"),
    )
    result = BacktestEngine(RegimeAwareTechnicalStrategy(), config).run(
        history=history,
        benchmark_symbol=universe.benchmark_symbol,
    )

    benchmark_count = len(history[universe.benchmark_symbol])
    train_bars = min(500, max(60, benchmark_count // 2))
    test_bars = min(100, max(20, benchmark_count // 10))
    evaluator = WalkForwardEvaluator(
        RegimeAwareTechnicalStrategy,
        backtest_config=config,
        walk_forward_config=WalkForwardConfig(
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=test_bars,
        ),
    )
    windows = evaluator.evaluate(
        history=history,
        benchmark_symbol=universe.benchmark_symbol,
    )

    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "data_feed": "iex",
        "timeframe": "5Min",
        "history_start": start.isoformat(),
        "history_end": end.isoformat(),
        "starting_nav": str(result.starting_nav),
        "ending_nav": str(result.ending_nav),
        "total_return": str(result.total_return),
        "max_drawdown": str(result.max_drawdown),
        "total_costs": str(result.total_costs),
        "trade_count": result.trade_count,
        "decision_points": len(result.points),
        "walk_forward_windows": len(windows),
        "walk_forward_returns": [str(window.result.total_return) for window in windows],
        "candidate_symbols": list(universe.symbols),
        "benchmark_symbol": universe.benchmark_symbol,
        "paper_orders_submitted": 0,
    }

    output = Path("state/m4-baseline-validation.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Project Fifty M4 historical validation: PASS")
    for key in (
        "starting_nav",
        "ending_nav",
        "total_return",
        "max_drawdown",
        "total_costs",
        "trade_count",
        "decision_points",
        "walk_forward_windows",
        "paper_orders_submitted",
    ):
        print(f"{key}={payload[key]}")


if __name__ == "__main__":
    main()
