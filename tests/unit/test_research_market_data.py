from datetime import UTC, datetime

import httpx
from pydantic import SecretStr

from project_fifty.market_data.alpaca import AlpacaMarketDataConfig
from project_fifty.market_data.research import AlpacaResearchMarketDataClient


def test_research_history_requests_split_adjustment_across_windows() -> None:
    adjustments: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/stocks/bars"
        adjustments.append(request.url.params.get("adjustment"))
        return httpx.Response(
            200,
            json={"bars": {}, "next_page_token": None},
        )

    config = AlpacaMarketDataConfig(
        api_key=SecretStr("key"),
        api_secret=SecretStr("secret"),
    )
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=config.base_url,
    )
    data = AlpacaResearchMarketDataClient(config, client=client)

    result = data.get_bars(
        ("NVDA", "SPY"),
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 4, 1, tzinfo=UTC),
        timeframe="1Day",
    )

    assert result == {"NVDA": (), "SPY": ()}
    assert len(adjustments) > 1
    assert set(adjustments) == {"split"}
