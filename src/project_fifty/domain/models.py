from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    cash_gbp: Decimal
    positions: dict[str, Position] = Field(default_factory=dict)
    nav_gbp: Decimal
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("cash_gbp", "nav_gbp")
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
    notional_gbp: Decimal | None = None
    reduce_fraction: Decimal | None = None
    reference_price_gbp: Decimal
    reference_price_timestamp: datetime
    estimated_fee_gbp: Decimal
    estimated_slippage_gbp: Decimal
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "reference_price_gbp",
        "estimated_fee_gbp",
        "estimated_slippage_gbp",
        "quantity",
        "notional_gbp",
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

    @field_validator("reference_price_gbp")
    @classmethod
    def _reference_price_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("must be positive")
        return value


class OrderIntent(StrictModel):
    intent_id: str
    idempotency_key: str
    proposal_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    reference_price_gbp: Decimal

    @classmethod
    def create(
        cls,
        *,
        idempotency_key: str,
        proposal_id: str,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        reference_price_gbp: Decimal,
    ) -> "OrderIntent":
        return cls(
            intent_id=str(uuid4()),
            idempotency_key=idempotency_key,
            proposal_id=proposal_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            reference_price_gbp=reference_price_gbp,
        )

    @field_validator("quantity", "reference_price_gbp")
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
    fill_price_gbp: Decimal
    fee_gbp: Decimal
    slippage_gbp: Decimal
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not parsed.is_finite():
        raise ValueError("must be finite")
    return parsed
