from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator

from project_fifty.strategies.contracts import MarketBar

DATA_BASE_URL = "https://data.alpaca.markets"
JsonObject = dict[str, Any]


class AlpacaMarketDataConfig(BaseModel):
    """Read-only Alpaca stock-market-data configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    api_secret: SecretStr
    base_url: str = DATA_BASE_URL
    feed: str = "iex"
    currency: str = "USD"
    timeout_seconds: float = 10.0
    max_pages: int = 25

    @field_validator("base_url")
    @classmethod
    def _data_endpoint_only(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if normalized != DATA_BASE_URL:
            raise ValueError("M4 permits the Alpaca market-data endpoint only")
        return normalized

    @field_validator("feed")
    @classmethod
    def _iex_only(cls, value: str) -> str:
        normalized = value.lower()
        if normalized != "iex":
            raise ValueError("M4 uses the IEX feed explicitly")
        return normalized

    @field_validator("currency")
    @classmethod
    def _usd_only(cls, value: str) -> str:
        normalized = value.upper()
        if normalized != "USD":
            raise ValueError("Alpaca US-equity market data must use USD")
        return normalized

    @field_validator("timeout_seconds")
    @classmethod
    def _positive_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value

    @field_validator("max_pages")
    @classmethod
    def _positive_pages(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_pages must be positive")
        return value

    @model_validator(mode="after")
    def _credentials_required(self) -> "AlpacaMarketDataConfig":
        if not self.api_key.get_secret_value().strip():
            raise ValueError("Alpaca paper API key is required")
        if not self.api_secret.get_secret_value().strip():
            raise ValueError("Alpaca paper API secret is required")
        return self

    @classmethod
    def from_env(cls) -> "AlpacaMarketDataConfig":
        return cls(
            api_key=SecretStr(os.getenv("ALPACA_PAPER_API_KEY", "")),
            api_secret=SecretStr(os.getenv("ALPACA_PAPER_API_SECRET", "")),
            base_url=os.getenv("ALPACA_DATA_BASE_URL", DATA_BASE_URL),
            feed=os.getenv("ALPACA_DATA_FEED", "iex"),
        )


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    bid: Decimal
    ask: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("quote symbol is required")
        if not self.bid.is_finite() or not self.ask.is_finite():
            raise ValueError("quote prices must be finite")
        if self.bid < 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("invalid bid/ask quote")
        if self.timestamp.tzinfo is None:
            raise ValueError("quote timestamp must be timezone-aware")

    @property
    def midpoint(self) -> Decimal:
        if self.bid == 0:
            return self.ask
        return (self.bid + self.ask) / Decimal("2")


class AlpacaMarketDataClient:
    """Read-only client for historical bars and latest quotes."""

    def __init__(
        self,
        config: AlpacaMarketDataConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
        if str(self._client.base_url).rstrip("/") != config.base_url:
            if self._owns_client:
                self._client.close()
            raise ValueError("HTTP client must target the Alpaca market-data endpoint")
        self._client.headers.update(
            {
                "APCA-API-KEY-ID": config.api_key.get_secret_value(),
                "APCA-API-SECRET-KEY": config.api_secret.get_secret_value(),
                "Accept": "application/json",
            }
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "AlpacaMarketDataClient":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def get_bars(
        self,
        symbols: tuple[str, ...],
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "5Min",
        limit: int = 10000,
    ) -> dict[str, tuple[MarketBar, ...]]:
        clean_symbols = self._symbols(symbols)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("market-data bounds must be timezone-aware")
        if end <= start:
            raise ValueError("market-data end must be after start")
        if limit <= 0 or limit > 10000:
            raise ValueError("limit must be in [1, 10000]")

        bars_by_symbol: dict[str, dict[datetime, MarketBar]] = {
            symbol: {} for symbol in clean_symbols
        }
        page_token: str | None = None
        pages = 0

        while True:
            params = {
                "symbols": ",".join(clean_symbols),
                "timeframe": timeframe,
                "start": start.astimezone(UTC).isoformat(),
                "end": end.astimezone(UTC).isoformat(),
                "feed": self._config.feed,
                "currency": self._config.currency,
                "adjustment": "raw",
                "sort": "asc",
                "limit": str(limit),
            }
            if page_token is not None:
                params["page_token"] = page_token

            response = self._client.get("/v2/stocks/bars", params=params)
            response.raise_for_status()
            payload = self._json_object(response)
            raw_bars = payload.get("bars", {})
            if not isinstance(raw_bars, dict):
                raise ValueError("expected Alpaca bars object")

            for symbol, items in raw_bars.items():
                if symbol not in bars_by_symbol:
                    continue
                if not isinstance(items, list):
                    raise ValueError("expected Alpaca bar list")
                for item in items:
                    if not isinstance(item, dict):
                        raise ValueError("expected Alpaca bar object")
                    bar = self._parse_bar(cast(JsonObject, item))
                    if bar.timestamp > end.astimezone(UTC):
                        raise ValueError("Alpaca returned a bar after requested end")
                    bars_by_symbol[symbol][bar.timestamp] = bar

            pages += 1
            token = payload.get("next_page_token")
            if token in {None, ""}:
                break
            if not isinstance(token, str):
                raise ValueError("invalid Alpaca next_page_token")
            if pages >= self._config.max_pages:
                raise RuntimeError("Alpaca market-data pagination exceeded configured maximum")
            page_token = token

        return {
            symbol: tuple(sorted(items.values(), key=lambda bar: bar.timestamp))
            for symbol, items in bars_by_symbol.items()
        }

    def get_latest_quotes(self, symbols: tuple[str, ...]) -> dict[str, MarketQuote]:
        clean_symbols = self._symbols(symbols)
        response = self._client.get(
            "/v2/stocks/quotes/latest",
            params={
                "symbols": ",".join(clean_symbols),
                "feed": self._config.feed,
                "currency": self._config.currency,
            },
        )
        response.raise_for_status()
        payload = self._json_object(response)
        raw_quotes = payload.get("quotes", {})
        if not isinstance(raw_quotes, dict):
            raise ValueError("expected Alpaca quotes object")

        quotes: dict[str, MarketQuote] = {}
        for symbol, raw in raw_quotes.items():
            if symbol not in clean_symbols:
                continue
            if not isinstance(raw, dict):
                raise ValueError("expected Alpaca quote object")
            quote = cast(JsonObject, raw)
            quotes[symbol] = MarketQuote(
                symbol=symbol,
                bid=self._decimal(quote.get("bp") or "0"),
                ask=self._decimal(quote.get("ap")),
                timestamp=self._timestamp(quote.get("t")),
            )
        return quotes

    @staticmethod
    def _symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()}))
        if not cleaned:
            raise ValueError("at least one symbol is required")
        return cleaned

    @classmethod
    def _parse_bar(cls, raw: JsonObject) -> MarketBar:
        return MarketBar(
            timestamp=cls._timestamp(raw.get("t")),
            open=cls._decimal(raw.get("o")),
            high=cls._decimal(raw.get("h")),
            low=cls._decimal(raw.get("l")),
            close=cls._decimal(raw.get("c")),
            volume=cls._decimal(raw.get("v") or "0"),
        )

    @staticmethod
    def _timestamp(value: object) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError("missing Alpaca timestamp")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Alpaca timestamp must be timezone-aware")
        return parsed.astimezone(UTC)

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid decimal value from Alpaca: {value!r}") from exc
        if not parsed.is_finite():
            raise ValueError("non-finite decimal value from Alpaca")
        return parsed

    @staticmethod
    def _json_object(response: httpx.Response) -> JsonObject:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("expected Alpaca JSON object")
        return cast(JsonObject, payload)
