from datetime import UTC, datetime

import httpx
from pydantic import SecretStr

from project_fifty.market_data.alpaca import AlpacaMarketDataClient, AlpacaMarketDataConfig


def test_long_history_is_windowed_batched_and_deduplicated() -> None:
    requests: list[tuple[str, str, tuple[str, ...]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/stocks/bars"
        start = request.url.params["start"]
        end = request.url.params["end"]
        symbols = tuple(request.url.params["symbols"].split(","))
        requests.append((start, end, symbols))

        bars = {}
        for symbol in symbols:
            bars[symbol] = [
                {
                    "t": start,
                    "o": 100,
                    "h": 101,
                    "l": 99,
                    "c": 100,
                    "v": 1000,
                },
                {
                    "t": end,
                    "o": 100,
                    "h": 101,
                    "l": 99,
                    "c": 100,
                    "v": 1000,
                },
            ]
        return httpx.Response(200, json={"bars": bars, "next_page_token": None})

    config = AlpacaMarketDataConfig(
        api_key=SecretStr("key"),
        api_secret=SecretStr("secret"),
    )
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=config.base_url,
    )
    data = AlpacaMarketDataClient(config, client=client)
    symbols = ("AAPL", "AMZN", "GOOGL", "MSFT", "SPY")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 4, 1, tzinfo=UTC)

    history = data.get_bars(
        symbols,
        start=start,
        end=end,
        timeframe="30Min",
    )

    # 90 days -> three 30-day windows; five symbols -> batches of four and one.
    assert len(requests) == 6
    assert all(len(batch) <= 4 for _, _, batch in requests)
    assert set(history) == set(symbols)
    assert all(len(history[symbol]) == 4 for symbol in symbols)
    assert all(
        tuple(bar.timestamp for bar in history[symbol])
        == tuple(sorted({bar.timestamp for bar in history[symbol]}))
        for symbol in symbols
    )
    assert all(history[symbol][0].timestamp == start for symbol in symbols)
    assert all(history[symbol][-1].timestamp == end for symbol in symbols)
