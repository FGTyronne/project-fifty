from __future__ import annotations

from decimal import Decimal

from project_fifty.brokers.base import BrokerAdapter
from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    ExecutionReport,
    OrderIntent,
    OrderSide,
    OrderStatus,
    PortfolioState,
    RejectionReason,
    RiskDecision,
    TradeAction,
    TradeProposal,
)
from project_fifty.execution.state_machine import OrderStateMachine
from project_fifty.ledger.base import Ledger
from project_fifty.portfolio.reconcile import PortfolioReconciler
from project_fifty.risk.engine import RiskEngine


class ExecutionKernel:
    def __init__(
        self,
        *,
        settings: Settings,
        risk_engine: RiskEngine,
        broker: BrokerAdapter,
        ledger: Ledger,
        control: ControlState,
    ) -> None:
        self._settings = settings
        self._risk_engine = risk_engine
        self._broker = broker
        self._ledger = ledger
        self._control = control

        self._known_idempotency_keys: set[str] = set()
        self._reports: list[ExecutionReport] = []
        self._state_by_order: dict[str, OrderStateMachine] = {}

        self._hydrate_from_ledger()

    def _hydrate_from_ledger(self) -> None:
        for event in self._ledger.all_events():
            payload = event.payload
            if event.event_type == "risk_decision" and payload.get("approved"):
                key = payload.get("idempotency_key")
                if isinstance(key, str):
                    self._known_idempotency_keys.add(key)
            if event.event_type == "broker_execution_report":
                report = ExecutionReport.model_validate(payload)
                self._known_idempotency_keys.add(report.idempotency_key)
                self._reports.append(report)
            if event.event_type == "order_state_transition":
                order_id = payload.get("order_id")
                new_state = payload.get("to")
                if isinstance(order_id, str) and isinstance(new_state, str):
                    machine = self._state_by_order.setdefault(order_id, OrderStateMachine())
                    if machine.status.value == new_state:
                        continue
                    machine.transition(OrderStatus(new_state))

    def _authorized_portfolio(self) -> PortfolioState:
        mark_prices: dict[str, Decimal] = {}
        for report in self._reports:
            mark_prices[report.symbol] = report.fill_price
        if not mark_prices:
            mark_prices = {"TEST": Decimal("1")}
        return PortfolioReconciler.replay_events(
            starting_cash=self._settings.authorized_starting_cash,
            events=self._reports,
            mark_prices=mark_prices,
            currency=self._settings.account_currency,
        )

    def _transition_order(self, order_id: str, to_state: OrderStatus) -> bool:
        machine = self._state_by_order.setdefault(order_id, OrderStateMachine())
        try:
            machine.transition(to_state)
        except ValueError:
            return False
        self._ledger.append(
            "order_state_transition",
            {"order_id": order_id, "from": machine.status.value, "to": to_state.value},
        )
        return True

    def _derive_intent(self, proposal: TradeProposal) -> OrderIntent | None:
        if proposal.action in {TradeAction.HOLD, TradeAction.CANCEL}:
            return None

        authorized_portfolio = self._authorized_portfolio()
        position = authorized_portfolio.positions.get(proposal.symbol)
        current_qty = position.quantity if position is not None else Decimal("0")

        if proposal.action in {TradeAction.BUY, TradeAction.ADD}:
            if proposal.quantity is None:
                return None
            return OrderIntent.create(
                idempotency_key=proposal.idempotency_key,
                proposal_id=proposal.proposal_id,
                symbol=proposal.symbol,
                side=OrderSide.BUY,
                quantity=proposal.quantity,
                reference_price=proposal.reference_price,
                currency=proposal.quote_currency,
            )

        quantity = proposal.quantity or Decimal("0")
        if proposal.action == TradeAction.REDUCE:
            if proposal.reduce_fraction is None:
                return None
            quantity = current_qty * proposal.reduce_fraction
        if proposal.action == TradeAction.EXIT:
            quantity = current_qty

        return OrderIntent.create(
            idempotency_key=proposal.idempotency_key,
            proposal_id=proposal.proposal_id,
            symbol=proposal.symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            reference_price=proposal.reference_price,
            currency=proposal.quote_currency,
        )

    def handle_proposal(
        self,
        proposal: TradeProposal,
    ) -> tuple[RiskDecision, ExecutionReport | None]:
        self._ledger.append("proposal_created", proposal.model_dump(mode="json"))

        intent = self._derive_intent(proposal)
        if intent is not None:
            self._ledger.append("order_intent_created", intent.model_dump(mode="json"))
            self._ledger.append(
                "order_state_transition",
                {"order_id": intent.intent_id, "from": "CREATED", "to": "CREATED"},
            )

        authorized_portfolio = self._authorized_portfolio()
        position = authorized_portfolio.positions.get(proposal.symbol)
        current_qty = position.quantity if position is not None else Decimal("0")

        decision = self._risk_engine.evaluate(
            proposal,
            intent=intent,
            authorized_cash=authorized_portfolio.cash,
            position_qty=current_qty,
            control=self._control,
            known_idempotency_keys=self._known_idempotency_keys,
        )
        decision_payload = decision.model_dump(mode="json")
        decision_payload["idempotency_key"] = proposal.idempotency_key
        self._ledger.append("risk_decision", decision_payload)

        if not decision.approved:
            return decision, None

        self._known_idempotency_keys.add(proposal.idempotency_key)

        if proposal.action == TradeAction.HOLD:
            return decision, None

        if proposal.action == TradeAction.CANCEL:
            assert proposal.cancel_order_id is not None
            self._ledger.append(
                "cancellation_requested",
                {
                    "proposal_id": proposal.proposal_id,
                    "cancel_order_id": proposal.cancel_order_id,
                },
            )
            cancelled = self._broker.cancel(proposal.cancel_order_id)
            self._ledger.append("broker_cancelled", cancelled.model_dump(mode="json"))
            report = ExecutionReport(
                report_id=f"cancel-{cancelled.broker_order_id}",
                broker_order_id=cancelled.broker_order_id,
                idempotency_key=proposal.idempotency_key,
                symbol=cancelled.symbol,
                side=cancelled.side,
                status=OrderStatus.CANCELLED,
                fill_quantity=Decimal("0"),
                fill_price=proposal.reference_price,
                fee=Decimal("0"),
                slippage=Decimal("0"),
                currency=proposal.quote_currency,
            )
            self._ledger.append("broker_execution_report", report.model_dump(mode="json"))
            return decision, report

        if intent is None:
            denied = RiskDecision(approved=False, reason=RejectionReason.INVALID_SCHEMA)
            self._ledger.append("risk_decision", denied.model_dump(mode="json"))
            return denied, None

        machine = self._state_by_order.setdefault(intent.intent_id, OrderStateMachine())
        try:
            machine.transition(OrderStatus.VALIDATED)
            self._ledger.append(
                "order_state_transition",
                {"order_id": intent.intent_id, "from": "CREATED", "to": "VALIDATED"},
            )
            machine.transition(OrderStatus.SUBMITTING)
            self._ledger.append(
                "order_state_transition",
                {"order_id": intent.intent_id, "from": "VALIDATED", "to": "SUBMITTING"},
            )
        except ValueError:
            denied = RiskDecision(
                approved=False,
                reason=RejectionReason.INVALID_ORDER_STATE_TRANSITION,
            )
            self._ledger.append("risk_decision", denied.model_dump(mode="json"))
            return denied, None

        self._ledger.append("broker_submission_attempt", {"intent_id": intent.intent_id})
        report = self._broker.submit(intent)
        self._ledger.append("broker_execution_report", report.model_dump(mode="json"))

        target_state = report.status
        if target_state not in {
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.UNKNOWN,
            OrderStatus.REJECTED,
        }:
            target_state = OrderStatus.UNKNOWN
        machine.transition(target_state)
        self._ledger.append(
            "order_state_transition",
            {
                "order_id": intent.intent_id,
                "from": OrderStatus.SUBMITTING.value,
                "to": target_state.value,
            },
        )

        self._reports.append(report)

        if report.status == OrderStatus.UNKNOWN:
            return decision, report

        authorized_after = self._authorized_portfolio()
        self._ledger.append("reconciliation_result", authorized_after.model_dump(mode="json"))
        self._ledger.append(
            "portfolio_nav_snapshot",
            {"nav": str(authorized_after.nav), "cash": str(authorized_after.cash)},
        )
        return decision, report
