from __future__ import annotations

from decimal import Decimal

from project_fifty.brokers.base import BrokerAdapter
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    ExecutionReport,
    OrderIntent,
    OrderSide,
    OrderStatus,
    RejectionReason,
    RiskDecision,
    TradeAction,
    TradeProposal,
)
from project_fifty.ledger.base import Ledger
from project_fifty.portfolio.reconcile import PortfolioReconciler
from project_fifty.risk.engine import RiskEngine


class ExecutionKernel:
    def __init__(
        self,
        *,
        risk_engine: RiskEngine,
        broker: BrokerAdapter,
        ledger: Ledger,
        control: ControlState,
    ) -> None:
        self._risk_engine = risk_engine
        self._broker = broker
        self._ledger = ledger
        self._control = control

    def handle_proposal(
        self,
        proposal: TradeProposal,
    ) -> tuple[RiskDecision, ExecutionReport | None]:
        self._ledger.append("proposal_created", proposal.model_dump(mode="json"))

        portfolio = self._broker.get_portfolio()
        position_qty = portfolio.positions.get(proposal.symbol, None)
        current_qty = position_qty.quantity if position_qty is not None else Decimal("0")

        decision = self._risk_engine.evaluate(
            proposal,
            portfolio_cash_gbp=portfolio.cash_gbp,
            position_qty=current_qty,
            control=self._control,
        )
        self._ledger.append("risk_decision", decision.model_dump(mode="json"))

        if not decision.approved:
            return decision, None

        if proposal.action == TradeAction.HOLD:
            return decision, None

        if proposal.action == TradeAction.CANCEL:
            self._ledger.append("cancellation_requested", {"proposal_id": proposal.proposal_id})
            return decision, None

        quantity = proposal.quantity or Decimal("0")
        side = OrderSide.BUY
        if proposal.action in {TradeAction.SELL, TradeAction.REDUCE, TradeAction.EXIT}:
            side = OrderSide.SELL
            if proposal.action == TradeAction.REDUCE and proposal.reduce_fraction is not None:
                quantity = current_qty * proposal.reduce_fraction
            elif proposal.action == TradeAction.EXIT:
                quantity = current_qty

        if quantity <= 0:
            denied = RiskDecision(approved=False, reason=RejectionReason.NEGATIVE_OR_ZERO_INPUT)
            self._ledger.append("risk_decision", denied.model_dump(mode="json"))
            return denied, None

        intent = OrderIntent.create(
            idempotency_key=proposal.idempotency_key,
            proposal_id=proposal.proposal_id,
            symbol=proposal.symbol,
            side=side,
            quantity=quantity,
            reference_price_gbp=proposal.reference_price_gbp,
        )
        self._ledger.append("order_intent_created", intent.model_dump(mode="json"))

        self._ledger.append("broker_submission_attempt", {"intent_id": intent.intent_id})
        report = self._broker.submit(intent)
        self._ledger.append("broker_execution_report", report.model_dump(mode="json"))

        if report.status == OrderStatus.UNKNOWN:
            return decision, report

        reconciled = PortfolioReconciler.reconcile_from_broker(self._broker.get_portfolio())
        self._ledger.append("reconciliation_result", reconciled.model_dump(mode="json"))
        self._ledger.append(
            "portfolio_nav_snapshot",
            {"nav_gbp": str(reconciled.nav_gbp), "cash_gbp": str(reconciled.cash_gbp)},
        )
        return decision, report
