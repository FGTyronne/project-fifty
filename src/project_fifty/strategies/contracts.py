from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from project_fifty.domain.models import PortfolioState


class StrictStrategyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MarketBar(StrictStrategyModel):
    """One point-in-time OHLCV observation available to a strategy."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @field_validator("open", "high", "low", "close")
    @classmethod
    def _validate_prices(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("OHLC prices must be finite and positive")
        return value

    @field_validator("volume")
    @classmethod
    def _validate_volume(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("volume must be finite and non-negative")
        return value

    @model_validator(mode="after")
    def _validate_ohlc(self) -> "MarketBar":
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to open/close/low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to open/close/high")
        return self


class StrategyContext(StrictStrategyModel):
    """Point-in-time inputs supplied to a strategy provider."""

    as_of: datetime
    currency: str
    portfolio: PortfolioState
    reference_prices: dict[str, Decimal]
    reference_price_timestamps: dict[str, datetime]
    market_state_hash: str
    history: dict[str, tuple[MarketBar, ...]] = Field(default_factory=dict)
    benchmark_symbol: str | None = None

    @field_validator("reference_prices")
    @classmethod
    def _validate_reference_prices(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        if not value:
            raise ValueError("reference_prices must not be empty")
        for symbol, price in value.items():
            if not symbol:
                raise ValueError("reference price symbol must not be empty")
            if not price.is_finite() or price <= 0:
                raise ValueError("reference prices must be finite and positive")
        return value

    @model_validator(mode="after")
    def _validate_currency_timestamps_and_history(self) -> "StrategyContext":
        if self.currency != self.portfolio.currency:
            raise ValueError("strategy context currency must match portfolio currency")
        if set(self.reference_prices) != set(self.reference_price_timestamps):
            raise ValueError("every reference price must have exactly one timestamp")
        for timestamp in self.reference_price_timestamps.values():
            if timestamp > self.as_of:
                raise ValueError("reference price timestamp cannot be in the future")
        for symbol, bars in self.history.items():
            previous: datetime | None = None
            for bar in bars:
                if bar.timestamp > self.as_of:
                    raise ValueError(f"future bar detected for {symbol}")
                if previous is not None and bar.timestamp <= previous:
                    raise ValueError(f"history must be strictly increasing for {symbol}")
                previous = bar.timestamp
        if self.benchmark_symbol is not None and self.benchmark_symbol not in self.history:
            raise ValueError("benchmark_symbol must exist in history")
        return self


class TargetPortfolio(StrictStrategyModel):
    """Desired strategy exposure, never execution authority."""

    as_of: datetime
    currency: str
    weights: dict[str, Decimal] = Field(default_factory=dict)
    cash_weight: Decimal
    strategy_id: str
    strategy_version: str
    confidence: Decimal
    market_state_hash: str
    evidence: dict[str, str] = Field(default_factory=dict)

    @field_validator("cash_weight", "confidence")
    @classmethod
    def _validate_unit_interval(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1:
            raise ValueError("value must be finite and between 0 and 1")
        return value

    @field_validator("weights")
    @classmethod
    def _validate_weights(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        for symbol, weight in value.items():
            if not symbol:
                raise ValueError("target symbol must not be empty")
            if not weight.is_finite() or weight < 0 or weight > 1:
                raise ValueError("target weights must be finite and between 0 and 1")
        return value

    @model_validator(mode="after")
    def _validate_total_weight(self) -> "TargetPortfolio":
        total = sum(self.weights.values(), start=Decimal("0")) + self.cash_weight
        if total != Decimal("1"):
            raise ValueError("target symbol weights plus cash_weight must equal exactly 1")
        if not self.strategy_id or not self.strategy_version or not self.market_state_hash:
            raise ValueError("strategy identity and market_state_hash are required")
        return self


class StrategyProvider(Protocol):
    """Any deterministic, ML, RL or AI strategy must implement this boundary."""

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        """Return desired portfolio weights using only point-in-time context."""
        ...
