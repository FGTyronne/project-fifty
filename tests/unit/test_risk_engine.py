from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.control.state import ControlState
from project_fifty.domain.models import ExperimentMode, OrderIntent, OrderSide, RejectionReason, TradeAction
from project_fifty.risk.engine import RiskEngine
from tests.conftest import make_proposal


def _intent_for_buy() -> OrderIntent:
    return OrderIntent.create(
        idempotency_key="k1",
        proposal_id="p1",
        symbol="TEST",
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        reference_price=Decimal("50"),
        currency="USD",
    )


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
        intent=_intent_for_buy(),
        authorized_cash=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
        known_idempotency_keys=set(),
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
    intent = OrderIntent.create(
        idempotency_key="k2",
        proposal_id="p2",
        symbol="TEST",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        reference_price=Decimal("5"),
        currency="USD",
    )
    decision = engine.evaluate(
        proposal,
        intent=intent,
        authorized_cash=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
        known_idempotency_keys=set(),
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
    intent = OrderIntent.create(
        idempotency_key="k3",
        proposal_id="p3",
        symbol="TEST",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        reference_price=Decimal("5"),
        currency="USD",
    )
    decision = engine.evaluate(
        proposal,
        intent=intent,
        authorized_cash=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
        known_idempotency_keys=set(),
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
        intent = OrderIntent.create(
            idempotency_key=f"{mode.value}-k",
            proposal_id=f"{mode.value}-p",
            symbol="TEST",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            reference_price=Decimal("5"),
            currency="USD",
        )
        decision = engine.evaluate(
            proposal,
            intent=intent,
            authorized_cash=Decimal("50"),
            position_qty=Decimal("0"),
            control=control,
            known_idempotency_keys=set(),
        )
        assert decision.reason == RejectionReason.MODE_RESTRICTION


def test_dead_cannot_transition_even_manual() -> None:
    control = ControlState(mode=ExperimentMode.DEAD)
    for automatic in (True, False):
        try:
            control.transition_mode(ExperimentMode.NORMAL, automatic=automatic)
        except ValueError:
            pass
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
    intent = OrderIntent.create(
        idempotency_key="k4",
        proposal_id="p4",
        symbol="TEST",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        reference_price=Decimal("5"),
        currency="USD",
    )
    decision = engine.evaluate(
        proposal,
        intent=intent,
        authorized_cash=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
        known_idempotency_keys=set(),
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
    intent = OrderIntent.create(
        idempotency_key="dup-key",
        proposal_id="p5",
        symbol="TEST",
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        reference_price=Decimal("5"),
        currency="USD",
    )
    first = engine.evaluate(
        proposal,
        intent=intent,
        authorized_cash=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
        known_idempotency_keys=set(),
    )
    second = engine.evaluate(
        proposal,
        intent=intent,
        authorized_cash=Decimal("50"),
        position_qty=Decimal("0"),
        control=control,
        known_idempotency_keys={"dup-key"},
    )
    assert first.reason == RejectionReason.APPROVED
    assert second.reason == RejectionReason.DUPLICATE_IDEMPOTENCY_KEY
