from __future__ import annotations

import os
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

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

    @classmethod
    def from_env(cls) -> "Settings":
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
            "max_order_notional": parse_decimal(
                os.getenv("PROJECT_FIFTY_MAX_ORDER_NOTIONAL", "50.00")
            ),
        }
        return cls.model_validate(data)
