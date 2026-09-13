from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    ExperimentMode,
    OrderIntent,
    OrderSide,
    RejectionReason,
    RiskDecision,
    TradeAction,
    TradeProposal,
)


class RiskEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        proposal: TradeProposal,
        *,
        intent: OrderIntent | None,
        authorized_cash: Decimal,
        position_qty: Decimal,
        control: ControlState,
        known_idempotency_keys: set[str],
        now: datetime | None = None,
    ) -> RiskDecision:
        current_now = now or datetime.now(UTC)

        if proposal.action not in set(TradeAction):
            return RiskDecision(approved=False, reason=RejectionReason.ACTION_NOT_PERMITTED)

        if proposal.symbol not in self._settings.permitted_symbols:
            return RiskDecision(approved=False, reason=RejectionReason.INSTRUMENT_NOT_PERMITTED)

        if proposal.quote_currency != self._settings.account_currency:
            return RiskDecision(approved=False, reason=RejectionReason.CURRENCY_MISMATCH)

        if intent is not None and intent.currency != self._settings.account_currency:
            return RiskDecision(approved=False, reason=RejectionReason.CURRENCY_MISMATCH)

        if proposal.idempotency_key in known_idempotency_keys:
            return RiskDecision(approved=False, reason=RejectionReason.DUPLICATE_IDEMPOTENCY_KEY)

        if proposal.estimated_fee < 0 or proposal.estimated_slippage < 0:
            return RiskDecision(approved=False, reason=RejectionReason.ESTIMATED_COST_INVALID)

        age_seconds = (current_now - proposal.reference_price_timestamp).total_seconds()
        if age_seconds > self._settings.max_stale_seconds:
            return RiskDecision(approved=False, reason=RejectionReason.STALE_REFERENCE_PRICE)

        opening_action = proposal.action in {TradeAction.BUY, TradeAction.ADD}
        if control.kill_switch_active and opening_action:
            return RiskDecision(approved=False, reason=RejectionReason.KILL_SWITCH_ACTIVE)

        if control.mode in {ExperimentMode.SAFE, ExperimentMode.DEAD} and opening_action:
            return RiskDecision(approved=False, reason=RejectionReason.MODE_RESTRICTION)

        if proposal.action == TradeAction.CANCEL and not proposal.cancel_order_id:
            return RiskDecision(approved=False, reason=RejectionReason.CANCEL_TARGET_REQUIRED)

        if proposal.action in {TradeAction.HOLD, TradeAction.CANCEL}:
            return RiskDecision(approved=True, reason=RejectionReason.APPROVED)

        if intent is None:
            return RiskDecision(approved=False, reason=RejectionReason.INVALID_SCHEMA)

        if proposal.notional is not None and proposal.quantity is not None:
            if proposal.quantity * proposal.reference_price != proposal.notional:
                return RiskDecision(
                    approved=False,
                    reason=RejectionReason.NOTIONAL_QUANTITY_MISMATCH,
                )

        if proposal.reference_price != intent.reference_price:
            return RiskDecision(approved=False, reason=RejectionReason.NOTIONAL_QUANTITY_MISMATCH)

        if proposal.action in {TradeAction.BUY, TradeAction.ADD} and intent.side != OrderSide.BUY:
            return RiskDecision(approved=False, reason=RejectionReason.ACTION_NOT_PERMITTED)

        if proposal.action in {TradeAction.SELL, TradeAction.REDUCE, TradeAction.EXIT}:
            if intent.side != OrderSide.SELL:
                return RiskDecision(approved=False, reason=RejectionReason.ACTION_NOT_PERMITTED)
            if intent.quantity <= 0 or intent.quantity > position_qty:
                return RiskDecision(approved=False, reason=RejectionReason.SHORT_POSITION_FORBIDDEN)

        if intent.notional > self._settings.max_order_notional:
            return RiskDecision(approved=False, reason=RejectionReason.ORDER_NOTIONAL_LIMIT)

        if intent.side == OrderSide.BUY:
            total_cost = intent.notional + proposal.estimated_fee + proposal.estimated_slippage
            if total_cost > authorized_cash:
                return RiskDecision(approved=False, reason=RejectionReason.INSUFFICIENT_CASH)

        return RiskDecision(approved=True, reason=RejectionReason.APPROVED)
