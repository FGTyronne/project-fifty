from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    ExperimentMode,
    RejectionReason,
    RiskDecision,
    TradeAction,
    TradeProposal,
)


class RiskEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._seen_idempotency_keys: set[str] = set()

    def evaluate(
        self,
        proposal: TradeProposal,
        *,
        portfolio_cash_gbp: Decimal,
        position_qty: Decimal,
        control: ControlState,
        now: datetime | None = None,
    ) -> RiskDecision:
        current_now = now or datetime.now(UTC)

        if proposal.action not in set(TradeAction):
            return RiskDecision(approved=False, reason=RejectionReason.ACTION_NOT_PERMITTED)

        if proposal.symbol not in self._settings.permitted_symbols:
            return RiskDecision(approved=False, reason=RejectionReason.INSTRUMENT_NOT_PERMITTED)

        decimals_to_check: list[Decimal | None] = [
            proposal.quantity,
            proposal.notional_gbp,
            proposal.reduce_fraction,
            proposal.reference_price_gbp,
            proposal.estimated_fee_gbp,
            proposal.estimated_slippage_gbp,
        ]
        for value in decimals_to_check:
            if value is None:
                continue
            if not value.is_finite():
                return RiskDecision(approved=False, reason=RejectionReason.NON_FINITE_INPUT)

        if proposal.estimated_fee_gbp < 0 or proposal.estimated_slippage_gbp < 0:
            return RiskDecision(approved=False, reason=RejectionReason.ESTIMATED_COST_INVALID)

        age_seconds = (current_now - proposal.reference_price_timestamp).total_seconds()
        if age_seconds > self._settings.max_stale_seconds:
            return RiskDecision(approved=False, reason=RejectionReason.STALE_REFERENCE_PRICE)

        if proposal.idempotency_key in self._seen_idempotency_keys:
            return RiskDecision(approved=False, reason=RejectionReason.DUPLICATE_IDEMPOTENCY_KEY)

        opening_action = proposal.action in {TradeAction.BUY, TradeAction.ADD}
        if control.kill_switch_active and opening_action:
            return RiskDecision(approved=False, reason=RejectionReason.KILL_SWITCH_ACTIVE)

        if control.mode in {ExperimentMode.SAFE, ExperimentMode.DEAD} and opening_action:
            return RiskDecision(approved=False, reason=RejectionReason.MODE_RESTRICTION)

        if proposal.action in {TradeAction.BUY, TradeAction.ADD, TradeAction.SELL}:
            quantity = proposal.quantity
            if quantity is None or quantity <= 0:
                return RiskDecision(approved=False, reason=RejectionReason.NEGATIVE_OR_ZERO_INPUT)

        if proposal.action in {TradeAction.REDUCE, TradeAction.EXIT} and position_qty <= 0:
            return RiskDecision(approved=False, reason=RejectionReason.SHORT_POSITION_FORBIDDEN)

        if proposal.action == TradeAction.REDUCE:
            fraction = proposal.reduce_fraction
            if fraction is None or fraction <= 0 or fraction > 1:
                return RiskDecision(approved=False, reason=RejectionReason.NEGATIVE_OR_ZERO_INPUT)

        if proposal.action in {TradeAction.SELL, TradeAction.REDUCE, TradeAction.EXIT}:
            sell_qty = proposal.quantity or Decimal("0")
            if proposal.action == TradeAction.REDUCE and proposal.reduce_fraction is not None:
                sell_qty = position_qty * proposal.reduce_fraction
            if proposal.action == TradeAction.EXIT:
                sell_qty = position_qty
            if sell_qty <= 0 or sell_qty > position_qty:
                return RiskDecision(approved=False, reason=RejectionReason.SHORT_POSITION_FORBIDDEN)

        if proposal.action in {TradeAction.BUY, TradeAction.ADD}:
            if proposal.quantity is None:
                return RiskDecision(approved=False, reason=RejectionReason.NEGATIVE_OR_ZERO_INPUT)
            notional = proposal.quantity * proposal.reference_price_gbp
            if proposal.notional_gbp is not None:
                notional = proposal.notional_gbp
            if notional > self._settings.max_order_notional_gbp:
                return RiskDecision(approved=False, reason=RejectionReason.ORDER_NOTIONAL_LIMIT)
            total_cost = notional + proposal.estimated_fee_gbp + proposal.estimated_slippage_gbp
            if total_cost > portfolio_cash_gbp:
                return RiskDecision(approved=False, reason=RejectionReason.INSUFFICIENT_CASH)

        self._seen_idempotency_keys.add(proposal.idempotency_key)
        return RiskDecision(approved=True, reason=RejectionReason.APPROVED)
