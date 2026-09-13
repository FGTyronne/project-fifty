from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


class AlpacaPaperConfig(BaseModel):
    """Runtime-only Alpaca paper credentials and connection settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    api_secret: SecretStr
    base_url: str = PAPER_BASE_URL
    timeout_seconds: float = 10.0
    request_log_path: Path | None = Path("state/alpaca-request-ids.jsonl")
    currency: str = "USD"

    @field_validator("base_url")
    @classmethod
    def _paper_endpoint_only(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if normalized != PAPER_BASE_URL:
            raise ValueError("M2 permits the Alpaca paper endpoint only")
        return normalized

    @field_validator("currency")
    @classmethod
    def _usd_only(cls, value: str) -> str:
        normalized = value.upper()
        if normalized != "USD":
            raise ValueError("Alpaca US-equity paper execution must use USD")
        return normalized

    @field_validator("timeout_seconds")
    @classmethod
    def _positive_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value

    @model_validator(mode="after")
    def _non_blank_credentials(self) -> "AlpacaPaperConfig":
        if not self.api_key.get_secret_value().strip():
            raise ValueError("Alpaca paper API key is required")
        if not self.api_secret.get_secret_value().strip():
            raise ValueError("Alpaca paper API secret is required")
        return self

    @classmethod
    def from_env(cls) -> "AlpacaPaperConfig":
        api_key = os.getenv("ALPACA_PAPER_API_KEY", "")
        api_secret = os.getenv("ALPACA_PAPER_API_SECRET", "")
        base_url = os.getenv("ALPACA_PAPER_BASE_URL", PAPER_BASE_URL)
        request_log = os.getenv(
            "ALPACA_PAPER_REQUEST_LOG",
            "state/alpaca-request-ids.jsonl",
        )
        return cls(
            api_key=SecretStr(api_key),
            api_secret=SecretStr(api_secret),
            base_url=base_url,
            request_log_path=Path(request_log) if request_log else None,
        )
