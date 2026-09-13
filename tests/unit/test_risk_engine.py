from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.control.state import ControlState
from project_fifty.domain.models import ExperimentMode, RejectionReason, TradeAction
from project_fifty.risk.engine import RiskEngine
from tests.conftest import make_proposal


def test_500_purchase_rejected_on_50_cash(settings: object, control: ControlState) -> None:
    engine = RiskEngine(settings)
    proposal = make_proposal(
        proposal_id="p1",
        key="k1",
        action=TradeAction.BUY,
        qty=Decimal("10"),
        price=Decimal("50"),
        notional=Decimal("500"),
    )
    decision = engine.evaluate(
        proposal,
        portfolio_cash_gbp=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
    )
    assert decision.approved is False
    assert decision.reason == RejectionReason.ORDER_NOTIONAL_LIMIT


def test_sell_cannot_create_short(settings: object, control: ControlState) -> None:
    engine = RiskEngine(settings)
    proposal = make_proposal(
        proposal_id="p2",
        key="k2",
        action=TradeAction.SELL,
        qty=Decimal("1"),
        price=Decimal("5"),
    )
    decision = engine.evaluate(
        proposal,
        portfolio_cash_gbp=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
    )
    assert decision.reason == RejectionReason.SHORT_POSITION_FORBIDDEN


def test_kill_switch_blocks_new_exposure(settings: object) -> None:
    engine = RiskEngine(settings)
    control = ControlState(kill_switch_active=True)
    proposal = make_proposal(
        proposal_id="p3",
        key="k3",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
    )
    decision = engine.evaluate(
        proposal,
        portfolio_cash_gbp=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
    )
    assert decision.reason == RejectionReason.KILL_SWITCH_ACTIVE


def test_safe_and_dead_block_new_exposure(settings: object) -> None:
    engine = RiskEngine(settings)
    for mode in (ExperimentMode.SAFE, ExperimentMode.DEAD):
        control = ControlState(mode=mode)
        proposal = make_proposal(
            proposal_id=f"{mode.value}-p",
            key=f"{mode.value}-k",
            action=TradeAction.BUY,
            qty=Decimal("1"),
            price=Decimal("5"),
        )
        decision = engine.evaluate(
            proposal,
            portfolio_cash_gbp=Decimal("50"),
            position_qty=Decimal("0"),
            control=control,
        )
        assert decision.reason == RejectionReason.MODE_RESTRICTION


def test_dead_cannot_auto_transition() -> None:
    control = ControlState(mode=ExperimentMode.DEAD)
    try:
        control.transition_mode(ExperimentMode.NORMAL, automatic=True)
    except ValueError:
        assert True
    else:
        raise AssertionError("expected transition to fail")


def test_stale_price_rejected(settings: object, control: ControlState) -> None:
    engine = RiskEngine(settings)
    stale = datetime.now(UTC) - timedelta(seconds=120)
    proposal = make_proposal(
        proposal_id="p4",
        key="k4",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
        ts=stale,
    )
    decision = engine.evaluate(
        proposal,
        portfolio_cash_gbp=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
        now=datetime.now(UTC),
    )
    assert decision.reason == RejectionReason.STALE_REFERENCE_PRICE


def test_deterministic_rejection_reason_codes(settings: object, control: ControlState) -> None:
    engine = RiskEngine(settings)
    proposal = make_proposal(
        proposal_id="p5",
        key="dup-key",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
    )
    first = engine.evaluate(
        proposal,
        portfolio_cash_gbp=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
    )
    second = engine.evaluate(
        proposal,
        portfolio_cash_gbp=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
    )
    assert first.reason == RejectionReason.APPROVED
    assert second.reason == RejectionReason.DUPLICATE_IDEMPOTENCY_KEY
