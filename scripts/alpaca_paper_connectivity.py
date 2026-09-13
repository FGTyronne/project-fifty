from __future__ import annotations

import json
from typing import Any

from project_fifty.brokers.alpaca import AlpacaPaperBroker, AlpacaPaperConfig


def _safe_field(data: dict[str, Any], key: str) -> object:
    value = data.get(key)
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


def main() -> int:
    """Authenticate to Alpaca paper trading without creating or changing orders."""

    config = AlpacaPaperConfig.from_env()
    with AlpacaPaperBroker(config) as broker:
        account = broker.get_account()
        clock = broker.get_clock()

    result = {
        "environment": "paper",
        "endpoint": config.base_url,
        "account_status": _safe_field(account, "status"),
        "trading_blocked": _safe_field(account, "trading_blocked"),
        "paper_cash": _safe_field(account, "cash"),
        "paper_buying_power": _safe_field(account, "buying_power"),
        "paper_equity": _safe_field(account, "equity"),
        "market_open": _safe_field(clock, "is_open"),
        "clock_timestamp": _safe_field(clock, "timestamp"),
        "authority_note": (
            "Broker paper balances are reconciliation data only; Project Fifty risk authority "
            "comes from its internal constitutional capital envelope."
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
