from __future__ import annotations

from datetime import UTC, datetime, timedelta

from project_fifty.brokers.alpaca.broker import AlpacaPaperBroker
from project_fifty.brokers.alpaca.config import AlpacaPaperConfig
from project_fifty.market_data.alpaca import AlpacaMarketDataClient, AlpacaMarketDataConfig
from project_fifty.market_data.universe import AlpacaUniverseBuilder


def main() -> None:
    paper_config = AlpacaPaperConfig.from_env()
    data_config = AlpacaMarketDataConfig.from_env()

    with AlpacaPaperBroker(paper_config) as broker:
        universe = AlpacaUniverseBuilder(broker).build()

    end = datetime.now(UTC) - timedelta(minutes=15)
    start = end - timedelta(days=14)
    with AlpacaMarketDataClient(data_config) as market_data:
        bars = market_data.get_bars(
            universe.all_symbols,
            start=start,
            end=end,
            timeframe="5Min",
        )
        quotes = market_data.get_latest_quotes(universe.all_symbols)

    missing_bars = [symbol for symbol in universe.all_symbols if not bars.get(symbol)]
    missing_quotes = [symbol for symbol in universe.all_symbols if symbol not in quotes]
    if missing_bars:
        raise RuntimeError(f"missing historical bars for: {','.join(missing_bars)}")
    if missing_quotes:
        raise RuntimeError(f"missing latest quotes for: {','.join(missing_quotes)}")

    print("Project Fifty M4 market-data smoke check: PASS")
    print("feed=iex")
    print(f"candidate_count={len(universe.symbols)}")
    print(f"benchmark={universe.benchmark_symbol}")
    print(f"symbols_with_bars={len([symbol for symbol in bars if bars[symbol]])}")
    print(f"symbols_with_quotes={len(quotes)}")
    print("orders_submitted=0")


if __name__ == "__main__":
    main()
