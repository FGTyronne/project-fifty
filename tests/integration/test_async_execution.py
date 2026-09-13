from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from project_fifty.brokers.simulated.broker import SimulatedBroker
from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    BrokerOrder,
    ExecutionReport,
    OrderIntent,
    OrderStatus,
    RejectionReason,
    TradeAction,
)
from project_fifty.execution.kernel import ExecutionKernel
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.risk.engine import RiskEngine
from tests.conftest import make_proposal


class AcknowledgingBroker(SimulatedBroker):
    def __init__(self) -> None:
        super().__init__(starting_cash=Decimal("100000"))
        self.submit_calls = 0
        self._known_orders: dict[str, OrderIntent] = {}

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        self.submit_calls += 1
        broker_order_id = f"ack-{intent.idempotency_key}"
        self._known_orders[broker_order_id] = intent
        return ExecutionReport(
            report_id=f"ack-report-{intent.idempotency_key}",
            broker_order_id=broker_order_id,
            idempotency_key=intent.idempotency_key,
            symbol=intent.symbol,
            side=intent.side,
            status=OrderStatus.ACKNOWLEDGED,
            fill_quantity=Decimal("0"),
            fill_price=intent.reference_price,
            fee=Decimal("0"),
            slippage=Decimal("0"),
            currency=intent.currency,
        )

    def cancel(self, broker_order_id: str) -> BrokerOrder:
        intent = self._known_orders[broker_order_id]
        return BrokerOrder(
            broker_order_id=broker_order_id,
            idempotency_key=intent.idempotency_key,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            status=OrderStatus.CANCELLED,
        )


def _settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"max_order_notional": Decimal("1000")})


def _kernel(
    settings: Settings,
    broker: AcknowledgingBroker,
    *,
    ledger: LocalAppendOnlyLedger | None = None,
) -> ExecutionKernel:
    return ExecutionKernel(
        settings=settings,
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=ledger or LocalAppendOnlyLedger(),
        control=ControlState(),
    )


def test_acknowledged_buy_reserves_cash_against_second_order(settings: Settings) -> None:
    project_settings = _settings(settings)
    broker = AcknowledgingBroker()
    kernel = _kernel(project_settings, broker)

    first = make_proposal(
        proposal_id="first",
        key="first",
        action=TradeAction.BUY,
        qty=Decimal("3"),
        price=Decimal("10"),
        notional=Decimal("30"),
    )
    second = make_proposal(
        proposal_id="second",
        key="second",
        action=TradeAction.BUY,
        qty=Decimal("3"),
        price=Decimal("10"),
        notional=Decimal("30"),
    )

    first_decision, first_report = kernel.handle_proposal(first)
    second_decision, second_report = kernel.handle_proposal(second)

    assert first_decision.approved is True
    assert first_report is not None
    assert first_report.status == OrderStatus.ACKNOWLEDGED
    assert second_decision.approved is False
    assert second_decision.reason == RejectionReason.INSUFFICIENT_CASH
    assert second_report is None
    assert broker.submit_calls == 1


def test_pending_order_reservation_survives_restart(settings: Settings, tmp_path: Path) -> None:
    project_settings = _settings(settings)
    ledger_path = tmp_path / "ledger.jsonl"
    first_broker = AcknowledgingBroker()
    first_kernel = _kernel(
        project_settings,
        first_broker,
        ledger=LocalAppendOnlyLedger(ledger_path),
    )
    first = make_proposal(
        proposal_id="first",
        key="first",
        action=TradeAction.BUY,
        qty=Decimal("3"),
        price=Decimal("10"),
        notional=Decimal("30"),
    )
    first_kernel.handle_proposal(first)

    restarted_broker = AcknowledgingBroker()
    restarted_kernel = _kernel(
        project_settings,
        restarted_broker,
        ledger=LocalAppendOnlyLedger(ledger_path),
    )
    second = make_proposal(
        proposal_id="second",
        key="second",
        action=TradeAction.BUY,
        qty=Decimal("3"),
        price=Decimal("10"),
        notional=Decimal("30"),
    )
    decision, report = restarted_kernel.handle_proposal(second)

    assert decision.approved is False
    assert decision.reason == RejectionReason.INSUFFICIENT_CASH
    assert report is None
    assert restarted_broker.submit_calls == 0


def test_reconciled_fill_releases_reservation_and_updates_portfolio(settings: Settings) -> None:
    project_settings = _settings(settings)
    broker = AcknowledgingBroker()
    kernel = _kernel(project_settings, broker)
    proposal = make_proposal(
        proposal_id="first",
        key="first",
        action=TradeAction.BUY,
        qty=Decimal("3"),
        price=Decimal("10"),
        notional=Decimal("30"),
    )
    _, acknowledged = kernel.handle_proposal(proposal)
    assert acknowledged is not None

    fill = ExecutionReport(
        report_id="fill-first",
        broker_order_id=acknowledged.broker_order_id,
        idempotency_key="first",
        symbol="TEST",
        side=acknowledged.side,
        status=OrderStatus.FILLED,
        fill_quantity=Decimal("3"),
        fill_price=Decimal("10"),
        fee=Decimal("0"),
        slippage=Decimal("0"),
        currency="USD",
    )
    portfolio = kernel.reconcile_execution_report(fill)

    assert portfolio.cash == Decimal("20")
    assert portfolio.positions["TEST"].quantity == Decimal("3")
    duplicate = kernel.reconcile_execution_report(fill)
    assert duplicate.cash == Decimal("20")
    assert duplicate.positions["TEST"].quantity == Decimal("3")


def test_cancelled_order_releases_reserved_cash(settings: Settings) -> None:
    project_settings = _settings(settings)
    broker = AcknowledgingBroker()
    kernel = _kernel(project_settings, broker)
    buy = make_proposal(
        proposal_id="first",
        key="first",
        action=TradeAction.BUY,
        qty=Decimal("4"),
        price=Decimal("10"),
        notional=Decimal("40"),
    )
    _, acknowledged = kernel.handle_proposal(buy)
    assert acknowledged is not None

    cancel = make_proposal(
        proposal_id="cancel-first",
        key="cancel-first",
        action=TradeAction.CANCEL,
        qty=None,
        price=Decimal("10"),
        cancel_order_id=acknowledged.broker_order_id,
    )
    cancel_decision, cancel_report = kernel.handle_proposal(cancel)
    assert cancel_decision.approved is True
    assert cancel_report is not None
    assert cancel_report.status == OrderStatus.CANCELLED

    replacement = make_proposal(
        proposal_id="replacement",
        key="replacement",
        action=TradeAction.BUY,
        qty=Decimal("4"),
        price=Decimal("10"),
        notional=Decimal("40"),
    )
    replacement_decision, replacement_report = kernel.handle_proposal(replacement)
    assert replacement_decision.approved is True
    assert replacement_report is not None
