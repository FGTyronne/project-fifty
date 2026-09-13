from __future__ import annotations

import os
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from project_fifty.domain.models import parse_decimal


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    env: str = Field(default="development", alias="PROJECT_FIFTY_ENV")
    log_level: str = Field(default="INFO", alias="PROJECT_FIFTY_LOG_LEVEL")
    inception_contribution_gbp: Decimal = Field(alias="PROJECT_FIFTY_STARTING_CASH_GBP")
    account_currency: str = "USD"
    authorized_starting_cash: Decimal = Decimal("50")
    kill_switch: bool = Field(default=False, alias="PROJECT_FIFTY_KILL_SWITCH")
    max_stale_seconds: int = 60
    max_order_notional: Decimal = Decimal("50")
    permitted_symbols: frozenset[str] = frozenset({"TEST"})

    @field_validator("permitted_symbols")
    @classmethod
    def _validate_permitted_symbols(cls, value: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(symbol.strip().upper() for symbol in value if symbol.strip())
        if not normalized:
            raise ValueError("permitted_symbols must not be empty")
        return normalized

    @field_validator("max_stale_seconds")
    @classmethod
    def _positive_stale_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("max_stale_seconds must be positive")
        return value

    @classmethod
    def from_env(cls) -> "Settings":
        symbol_text = os.getenv("PROJECT_FIFTY_PERMITTED_SYMBOLS", "TEST")
        symbols = frozenset(item for item in symbol_text.split(",") if item.strip())
        data: dict[str, object] = {
            "PROJECT_FIFTY_ENV": os.getenv("PROJECT_FIFTY_ENV", "development"),
            "PROJECT_FIFTY_LOG_LEVEL": os.getenv("PROJECT_FIFTY_LOG_LEVEL", "INFO"),
            "PROJECT_FIFTY_STARTING_CASH_GBP": parse_decimal(
                os.getenv("PROJECT_FIFTY_STARTING_CASH_GBP", "50.00")
            ),
            "account_currency": os.getenv("PROJECT_FIFTY_ACCOUNT_CURRENCY", "USD"),
            "authorized_starting_cash": parse_decimal(
                os.getenv("PROJECT_FIFTY_AUTHORIZED_STARTING_CASH", "50.00")
            ),
            "PROJECT_FIFTY_KILL_SWITCH": os.getenv("PROJECT_FIFTY_KILL_SWITCH", "false").lower()
            in {"1", "true", "yes", "on"},
            "max_stale_seconds": int(os.getenv("PROJECT_FIFTY_MAX_STALE_SECONDS", "60")),
            "max_order_notional": parse_decimal(
                os.getenv("PROJECT_FIFTY_MAX_ORDER_NOTIONAL", "50.00")
            ),
            "permitted_symbols": symbols,
        }
        return cls.model_validate(data)
