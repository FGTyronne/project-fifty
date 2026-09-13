from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import TradeAction, TradeProposal


@pytest.fixture
def settings() -> Settings:
    return Settings(
        PROJECT_FIFTY_ENV="test",
        PROJECT_FIFTY_LOG_LEVEL="INFO",
        PROJECT_FIFTY_STARTING_CASH_GBP=Decimal("50.00"),
        PROJECT_FIFTY_KILL_SWITCH=False,
        max_stale_seconds=30,
        max_order_notional_gbp=Decimal("50"),
        permitted_symbols=frozenset({"TEST"}),
    )


@pytest.fixture
def control() -> ControlState:
    return ControlState()


def make_proposal(
    *,
    proposal_id: str,
    key: str,
    action: TradeAction,
    qty: Decimal | None,
    price: Decimal,
    notional: Decimal | None = None,
    reduce_fraction: Decimal | None = None,
    ts: datetime | None = None,
) -> TradeProposal:
    return TradeProposal(
        proposal_id=proposal_id,
        idempotency_key=key,
        symbol="TEST",
        action=action,
        quantity=qty,
        notional_gbp=notional,
        reduce_fraction=reduce_fraction,
        reference_price_gbp=price,
        reference_price_timestamp=ts or datetime.now(UTC),
        estimated_fee_gbp=Decimal("0.01"),
        estimated_slippage_gbp=Decimal("0.01"),
    )
