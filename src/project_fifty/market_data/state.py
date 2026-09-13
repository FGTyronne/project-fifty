from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from project_fifty.market_data.alpaca import MarketQuote
from project_fifty.strategies.contracts import MarketBar


def market_state_hash(
    *,
    history: dict[str, tuple[MarketBar, ...]],
    quotes: dict[str, MarketQuote] | None = None,
) -> str:
    """Hash only point-in-time data supplied to the strategy."""

    payload: dict[str, object] = {"history": {}}
    history_payload: dict[str, list[dict[str, str]]] = {}
    for symbol in sorted(history):
        history_payload[symbol] = [
            {
                "t": bar.timestamp.isoformat(),
                "o": _decimal(bar.open),
                "h": _decimal(bar.high),
                "l": _decimal(bar.low),
                "c": _decimal(bar.close),
                "v": _decimal(bar.volume),
            }
            for bar in history[symbol]
        ]
    payload["history"] = history_payload

    if quotes is not None:
        payload["quotes"] = {
            symbol: {
                "t": quote.timestamp.isoformat(),
                "bid": _decimal(quote.bid),
                "ask": _decimal(quote.ask),
            }
            for symbol, quote in sorted(quotes.items())
        }

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decimal(value: Decimal) -> str:
    return format(value, "f")
