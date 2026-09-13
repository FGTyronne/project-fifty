from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from project_fifty.market_data.alpaca import (
    AlpacaMarketDataClient,
    JsonObject,
)
from project_fifty.strategies.contracts import MarketBar


class AlpacaResearchMarketDataClient(AlpacaMarketDataClient):
    """Historical-bars client for research/backtesting with split adjustment.

    The live/session market-data adapter intentionally retains its existing raw-bar default for
    reproducibility and because live portfolio reconciliation handles actual broker positions.
    Historical replay does not currently apply stock-split quantity events to simulated positions,
    so research bars must be split-adjusted to avoid fictitious P&L discontinuities.
    """

    adjustment = "split"

    def get_bars(
        self,
        symbols: tuple[str, ...],
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "1Day",
        limit: int = 10000,
    ) -> dict[str, tuple[MarketBar, ...]]:
        clean_symbols = self._symbols(symbols)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("market-data bounds must be timezone-aware")
        if end <= start:
            raise ValueError("market-data end must be after start")
        if limit <= 0 or limit > 10000:
            raise ValueError("limit must be in [1, 10000]")

        if end - start > timedelta(days=45):
            return self.get_bars_windowed(
                clean_symbols,
                start=start,
                end=end,
                timeframe=timeframe,
                chunk_days=30,
                symbol_batch_size=4,
                limit=limit,
            )

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
                "adjustment": self.adjustment,
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

    def get_bars_windowed(
        self,
        symbols: tuple[str, ...],
        *,
        start: datetime,
        end: datetime,
        timeframe: str,
        chunk_days: int = 30,
        symbol_batch_size: int = 4,
        limit: int = 10000,
    ) -> dict[str, tuple[MarketBar, ...]]:
        """Fetch long split-adjusted history without losing the adjustment at chunk boundaries."""
        clean_symbols = self._symbols(symbols)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("market-data bounds must be timezone-aware")
        if end <= start:
            raise ValueError("market-data end must be after start")
        if chunk_days <= 0:
            raise ValueError("chunk_days must be positive")
        if symbol_batch_size <= 0:
            raise ValueError("symbol_batch_size must be positive")

        combined: dict[str, dict[datetime, MarketBar]] = {
            symbol: {} for symbol in clean_symbols
        }
        cursor = start
        chunk = timedelta(days=chunk_days)
        requested_start = start.astimezone(UTC)
        requested_end = end.astimezone(UTC)

        while cursor < end:
            window_end = min(cursor + chunk, end)
            for offset in range(0, len(clean_symbols), symbol_batch_size):
                batch = clean_symbols[offset : offset + symbol_batch_size]
                bars = self.get_bars(
                    batch,
                    start=cursor,
                    end=window_end,
                    timeframe=timeframe,
                    limit=limit,
                )
                for symbol, observations in bars.items():
                    for bar in observations:
                        if bar.timestamp < requested_start or bar.timestamp > requested_end:
                            raise ValueError("windowed market data escaped requested bounds")
                        combined[symbol][bar.timestamp] = bar
            cursor = window_end

        return {
            symbol: tuple(sorted(items.values(), key=lambda bar: bar.timestamp))
            for symbol, items in combined.items()
        }
