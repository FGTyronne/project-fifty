from datetime import UTC, datetime
from decimal import Decimal

import httpx
from pydantic import SecretStr

from project_fifty.market_data.alpaca import AlpacaMarketDataClient, AlpacaMarketDataConfig


def test_historical_bars_paginate_and_latest_quotes_parse() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["APCA-API-KEY-ID"] == "key"
        assert request.headers["APCA-API-SECRET-KEY"] == "secret"
        calls.append(str(request.url))
        if request.url.path == "/v2/stocks/bars":
            page = request.url.params.get("page_token")
            if page is None:
                return httpx.Response(
                    200,
                    json={
                        "bars": {
                            "AAPL": [
                                {
                                    "t": "2026-09-11T14:30:00Z",
                                    "o": 100,
                                    "h": 102,
                                    "l": 99,
                                    "c": 101,
                                    "v": 1000,
                                }
                            ]
                        },
                        "next_page_token": "p2",
                    },
                )
            assert page == "p2"
            return httpx.Response(
                200,
                json={
                    "bars": {
                        "SPY": [
                            {
                                "t": "2026-09-11T14:30:00Z",
                                "o": 500,
                                "h": 502,
                                "l": 499,
                                "c": 501,
                                "v": 2000,
                            }
                        ]
                    },
                    "next_page_token": None,
                },
            )
        if request.url.path == "/v2/stocks/quotes/latest":
            return httpx.Response(
                200,
                json={
                    "quotes": {
                        "AAPL": {
                            "bp": 100,
                            "ap": 102,
                            "t": "2026-09-11T14:35:01Z",
                        },
                        "SPY": {
                            "bp": 500,
                            "ap": 502,
                            "t": "2026-09-11T14:35:01Z",
                        },
                    }
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    config = AlpacaMarketDataConfig(
        api_key=SecretStr("key"),
        api_secret=SecretStr("secret"),
    )
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url=config.base_url)
    data = AlpacaMarketDataClient(config, client=client)

    bars = data.get_bars(
        ("AAPL", "SPY"),
        start=datetime(2026, 9, 11, 14, 0, tzinfo=UTC),
        end=datetime(2026, 9, 11, 15, 0, tzinfo=UTC),
    )
    quotes = data.get_latest_quotes(("AAPL", "SPY"))

    assert len(bars["AAPL"]) == 1
    assert len(bars["SPY"]) == 1
    assert bars["AAPL"][0].close == Decimal("101")
    assert quotes["AAPL"].midpoint == Decimal("101")
    assert quotes["SPY"].midpoint == Decimal("501")
    assert len(calls) == 3


def test_market_data_config_rejects_non_data_endpoint() -> None:
    try:
        AlpacaMarketDataConfig(
            api_key=SecretStr("key"),
            api_secret=SecretStr("secret"),
            base_url="https://paper-api.alpaca.markets",
        )
    except ValueError as exc:
        assert "market-data endpoint" in str(exc)
    else:
        raise AssertionError("non-data endpoint should have been rejected")
