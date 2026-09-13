from __future__ import annotations

from decimal import Decimal

from project_fifty.brokers.base import BrokerAdapter
from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    ExecutionReport,
    ExperimentMode,
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

_TERMINAL_ORDER_STATES = {
    OrderStatus.FILLED,
    OrderStatus.REJECTED,
    OrderStatus.CANCELLED,
}


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
        self._report_ids: set[str] = set()
        self._state_by_order: dict[str, OrderStateMachine] = {}
        self._intents_by_key: dict[str, OrderIntent] = {}
        self._intent_id_by_key: dict[str, str] = {}
        self._estimated_cost_by_key: dict[str, Decimal] = {}
        self._broker_order_key: dict[str, str] = {}

        self._hydrate_from_ledger()

    def _hydrate_from_ledger(self) -> None:
        for event in self._ledger.all_events():
            payload = event.payload
            if event.event_type == "proposal_created":
                proposal = TradeProposal.model_validate(payload)
                self._estimated_cost_by_key[proposal.idempotency_key] = (
                    proposal.estimated_fee + proposal.estimated_slippage
                )
            if event.event_type == "risk_decision" and payload.get("approved"):
                key = payload.get("idempotency_key")
                if isinstance(key, str):
                    self._known_idempotency_keys.add(key)
            if event.event_type == "order_intent_created":
                intent = OrderIntent.model_validate(payload)
                self._intents_by_key[intent.idempotency_key] = intent
                self._intent_id_by_key[intent.idempotency_key] = intent.intent_id
            if event.event_type == "broker_execution_report":
                report = ExecutionReport.model_validate(payload)
                self._known_idempotency_keys.add(report.idempotency_key)
                if report.report_id not in self._report_ids:
                    self._reports.append(report)
                    self._report_ids.add(report.report_id)
                if report.idempotency_key in self._intents_by_key:
                    self._broker_order_key[report.broker_order_id] = report.idempotency_key
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
            if report.fill_price > 0:
                mark_prices[report.symbol] = report.fill_price
        if not mark_prices:
            mark_prices = {"TEST": Decimal("1")}
        return PortfolioReconciler.replay_events(
            starting_cash=self._settings.authorized_starting_cash,
            events=self._reports,
            mark_prices=mark_prices,
            currency=self._settings.account_currency,
        )

    def _reserved_cash(self) -> Decimal:
        reserved = Decimal("0")
        for key, intent in self._intents_by_key.items():
            if intent.side != OrderSide.BUY:
                continue
            intent_id = self._intent_id_by_key[key]
            machine = self._state_by_order.get(intent_id)
            status = machine.status if machine is not None else OrderStatus.CREATED
            if status in _TERMINAL_ORDER_STATES:
                continue

            filled_quantity = max(
                (
                    report.fill_quantity
                    for report in self._reports
                    if report.idempotency_key == key
                    and report.status in {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}
                ),
                default=Decimal("0"),
            )
            if filled_quantity > intent.quantity:
                raise ValueError("broker fill exceeds risk-approved order quantity")
            remaining_quantity = intent.quantity - filled_quantity
            if remaining_quantity <= 0:
                continue
            reserved += remaining_quantity * intent.reference_price
            reserved += self._estimated_cost_by_key.get(key, Decimal("0"))
        return reserved

    def _available_authorized_cash(self) -> Decimal:
        available = self._authorized_portfolio().cash - self._reserved_cash()
        return max(available, Decimal("0"))

    def _transition_order(self, order_id: str, to_state: OrderStatus) -> bool:
        machine = self._state_by_order.setdefault(order_id, OrderStateMachine())
        if machine.status == to_state:
            return True
        from_state = machine.status
        try:
            machine.transition(to_state)
        except ValueError:
            return False
        self._ledger.append(
            "order_state_transition",
            {"order_id": order_id, "from": from_state.value, "to": to_state.value},
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
        self._estimated_cost_by_key[proposal.idempotency_key] = (
            proposal.estimated_fee + proposal.estimated_slippage
        )

        intent = self._derive_intent(proposal)
        authorized_portfolio = self._authorized_portfolio()
        position = authorized_portfolio.positions.get(proposal.symbol)
        current_qty = position.quantity if position is not None else Decimal("0")

        decision = self._risk_engine.evaluate(
            proposal,
            intent=intent,
            authorized_cash=self._available_authorized_cash(),
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
            return decision, self._handle_cancel(proposal)

        if intent is None:
            denied = RiskDecision(approved=False, reason=RejectionReason.INVALID_SCHEMA)
            self._ledger.append("risk_decision", denied.model_dump(mode="json"))
            return denied, None

        self._intents_by_key[intent.idempotency_key] = intent
        self._intent_id_by_key[intent.idempotency_key] = intent.intent_id
        self._ledger.append("order_intent_created", intent.model_dump(mode="json"))
        self._ledger.append(
            "order_state_transition",
            {"order_id": intent.intent_id, "from": "CREATED", "to": "CREATED"},
        )

        if not self._transition_order(intent.intent_id, OrderStatus.VALIDATED):
            return self._state_transition_failure()
        if not self._transition_order(intent.intent_id, OrderStatus.SUBMITTING):
            return self._state_transition_failure()

        self._ledger.append("broker_submission_attempt", {"intent_id": intent.intent_id})
        report = self._broker.submit(intent)
        self._record_report(report)

        target_state = self._normalise_broker_state(report.status)
        if not self._transition_order(intent.intent_id, target_state):
            self._enter_safe_mode()
            raise RuntimeError("broker returned an invalid order state transition")

        if report.status == OrderStatus.UNKNOWN:
            return decision, report

        self._append_reconciliation()
        return decision, report

    def reconcile_execution_report(self, report: ExecutionReport) -> PortfolioState:
        if report.idempotency_key not in self._known_idempotency_keys:
            self._enter_safe_mode()
            raise ValueError("execution report references an unknown logical order")
        if report.currency != self._settings.account_currency:
            self._enter_safe_mode()
            raise ValueError("execution report currency mismatch")

        known_key = self._broker_order_key.get(report.broker_order_id)
        if known_key is not None and known_key != report.idempotency_key:
            self._enter_safe_mode()
            raise ValueError("broker order identity changed across reconciliation")

        self._record_report(report)
        intent_id = self._intent_id_by_key.get(report.idempotency_key)
        if intent_id is not None:
            target_state = self._normalise_broker_state(report.status)
            if not self._transition_order(intent_id, target_state):
                self._enter_safe_mode()
                raise ValueError("invalid reconciled broker order state transition")
        return self._append_reconciliation()

    def _handle_cancel(self, proposal: TradeProposal) -> ExecutionReport:
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

        original_key = self._broker_order_key.get(cancelled.broker_order_id)
        if cancelled.status == OrderStatus.CANCELLED and original_key is not None:
            intent_id = self._intent_id_by_key.get(original_key)
            if intent_id is not None and not self._transition_order(intent_id, OrderStatus.CANCELLED):
                self._enter_safe_mode()
                raise RuntimeError("invalid cancellation state transition")
        elif cancelled.status != OrderStatus.CANCELLED:
            self._enter_safe_mode()

        report_status = (
            OrderStatus.CANCELLED
            if cancelled.status == OrderStatus.CANCELLED
            else OrderStatus.UNKNOWN
        )
        report = ExecutionReport(
            report_id=f"cancel-{cancelled.broker_order_id}-{proposal.idempotency_key}",
            broker_order_id=cancelled.broker_order_id,
            idempotency_key=proposal.idempotency_key,
            symbol=cancelled.symbol,
            side=cancelled.side,
            status=report_status,
            fill_quantity=Decimal("0"),
            fill_price=proposal.reference_price,
            fee=Decimal("0"),
            slippage=Decimal("0"),
            currency=proposal.quote_currency,
            message=f"broker_cancel_status={cancelled.status.value}",
        )
        self._record_report(report)
        self._append_reconciliation()
        return report

    def _record_report(self, report: ExecutionReport) -> None:
        if report.report_id in self._report_ids:
            return
        self._ledger.append("broker_execution_report", report.model_dump(mode="json"))
        self._reports.append(report)
        self._report_ids.add(report.report_id)
        self._known_idempotency_keys.add(report.idempotency_key)
        if report.idempotency_key in self._intents_by_key:
            self._broker_order_key[report.broker_order_id] = report.idempotency_key

    def _append_reconciliation(self) -> PortfolioState:
        authorized = self._authorized_portfolio()
        self._ledger.append("reconciliation_result", authorized.model_dump(mode="json"))
        self._ledger.append(
            "portfolio_nav_snapshot",
            {
                "nav": str(authorized.nav),
                "cash": str(authorized.cash),
                "reserved_cash": str(self._reserved_cash()),
                "available_cash": str(self._available_authorized_cash()),
            },
        )
        return authorized

    def _state_transition_failure(self) -> tuple[RiskDecision, None]:
        self._enter_safe_mode()
        denied = RiskDecision(
            approved=False,
            reason=RejectionReason.INVALID_ORDER_STATE_TRANSITION,
        )
        self._ledger.append("risk_decision", denied.model_dump(mode="json"))
        return denied, None

    def _enter_safe_mode(self) -> None:
        if self._control.mode != ExperimentMode.DEAD:
            self._control.transition_mode(ExperimentMode.SAFE)

    @staticmethod
    def _normalise_broker_state(status: OrderStatus) -> OrderStatus:
        if status in {
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.CANCELLED,
            OrderStatus.UNKNOWN,
            OrderStatus.REJECTED,
        }:
            return status
        return OrderStatus.UNKNOWN
