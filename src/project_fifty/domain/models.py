from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    ADD = "ADD"
    REDUCE = "REDUCE"
    CANCEL = "CANCEL"
    EXIT = "EXIT"


class ExperimentMode(str, Enum):
    NORMAL = "NORMAL"
    DEFENSIVE = "DEFENSIVE"
    SAFE = "SAFE"
    DEAD = "DEAD"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class RejectionReason(str, Enum):
    APPROVED = "APPROVED"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    ACTION_NOT_PERMITTED = "ACTION_NOT_PERMITTED"
    INSTRUMENT_NOT_PERMITTED = "INSTRUMENT_NOT_PERMITTED"
    NON_FINITE_INPUT = "NON_FINITE_INPUT"
    NEGATIVE_OR_ZERO_INPUT = "NEGATIVE_OR_ZERO_INPUT"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    SHORT_POSITION_FORBIDDEN = "SHORT_POSITION_FORBIDDEN"
    ORDER_NOTIONAL_LIMIT = "ORDER_NOTIONAL_LIMIT"
    STALE_REFERENCE_PRICE = "STALE_REFERENCE_PRICE"
    DUPLICATE_IDEMPOTENCY_KEY = "DUPLICATE_IDEMPOTENCY_KEY"
    MODE_RESTRICTION = "MODE_RESTRICTION"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    ESTIMATED_COST_INVALID = "ESTIMATED_COST_INVALID"
    NOTIONAL_QUANTITY_MISMATCH = "NOTIONAL_QUANTITY_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    CANCEL_TARGET_REQUIRED = "CANCEL_TARGET_REQUIRED"
    INVALID_ORDER_STATE_TRANSITION = "INVALID_ORDER_STATE_TRANSITION"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Position(StrictModel):
    symbol: str
    quantity: Decimal
    average_price: Decimal

    @field_validator("quantity", "average_price")
    @classmethod
    def _finite_non_negative(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("must be finite")
        if value < 0:
            raise ValueError("must be non-negative")
        return value


class PortfolioState(StrictModel):
    cash: Decimal
    positions: dict[str, Position] = Field(default_factory=dict)
    nav: Decimal
    currency: str
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("cash", "nav")
    @classmethod
    def _finite_non_negative(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("must be finite")
        if value < 0:
            raise ValueError("must be non-negative")
        return value


class TradeProposal(StrictModel):
    proposal_id: str
    idempotency_key: str
    symbol: str
    action: TradeAction
    quantity: Decimal | None = None
    notional: Decimal | None = None
    reduce_fraction: Decimal | None = None
    reference_price: Decimal
    reference_price_timestamp: datetime
    estimated_fee: Decimal
    estimated_slippage: Decimal
    quote_currency: str
    cancel_order_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "reference_price",
        "estimated_fee",
        "estimated_slippage",
        "quantity",
        "notional",
        "reduce_fraction",
    )
    @classmethod
    def _validate_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite():
            raise ValueError("must be finite")
        if value < 0:
            raise ValueError("must be non-negative")
        return value

    @field_validator("reference_price")
    @classmethod
    def _reference_price_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @model_validator(mode="after")
    def _validate_reduce_fraction(self) -> "TradeProposal":
        if self.reduce_fraction is not None and self.reduce_fraction > Decimal("1"):
            raise ValueError("reduce_fraction must be <= 1")
        return self


class OrderIntent(StrictModel):
    intent_id: str
    idempotency_key: str
    proposal_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    reference_price: Decimal
    notional: Decimal
    currency: str

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        proposal_id: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        reference_price: Decimal,
        currency: str,
    ) -> "OrderIntent":
        return cls(
            intent_id=str(uuid4()),
            idempotency_key=idempotency_key,
            proposal_id=proposal_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            reference_price=reference_price,
            notional=quantity * reference_price,
            currency=currency,
        )

    @field_validator("quantity", "reference_price", "notional")
    @classmethod
    def _finite_positive(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("must be finite")
        if value <= 0:
            raise ValueError("must be positive")
        return value


class BrokerOrder(StrictModel):
    broker_order_id: str
    idempotency_key: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    status: OrderStatus


class ExecutionReport(StrictModel):
    report_id: str
    broker_order_id: str
    idempotency_key: str
    symbol: str
    side: OrderSide
    status: OrderStatus
    fill_quantity: Decimal
    fill_price: Decimal
    fee: Decimal
    slippage: Decimal
    currency: str
    message: str = ""


class RiskDecision(StrictModel):
    approved: bool
    reason: RejectionReason
    detail: str = ""


class LedgerEvent(StrictModel):
    event_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    prev_hash: str
    event_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not parsed.is_finite():
        raise ValueError("must be finite")
    return parsed
