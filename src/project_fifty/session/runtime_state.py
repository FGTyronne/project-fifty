from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from project_fifty.domain.models import ExecutionReport, OrderIntent, OrderSide, OrderStatus
from project_fifty.ledger.base import Ledger

_TERMINAL = {OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED}
_FILL_STATES = {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}


@dataclass(frozen=True)
class PendingOrder:
    idempotency_key: str
    intent_id: str
    reference_price: Decimal


def pending_orders(ledger: Ledger) -> tuple[PendingOrder, ...]:
    intents: dict[str, OrderIntent] = {}
    status_by_intent: dict[str, OrderStatus] = {}

    for event in ledger.all_events():
        if event.event_type == "order_intent_created":
            intent = OrderIntent.model_validate(event.payload)
            intents[intent.idempotency_key] = intent
        elif event.event_type == "order_state_transition":
            order_id = event.payload.get("order_id")
            target = event.payload.get("to")
            if isinstance(order_id, str) and isinstance(target, str):
                status_by_intent[order_id] = OrderStatus(target)

    result: list[PendingOrder] = []
    for key, intent in sorted(intents.items()):
        status = status_by_intent.get(intent.intent_id, OrderStatus.CREATED)
        if status in _TERMINAL:
            continue
        result.append(
            PendingOrder(
                idempotency_key=key,
                intent_id=intent.intent_id,
                reference_price=intent.reference_price,
            )
        )
    return tuple(result)


def expected_position_quantities(ledger: Ledger) -> dict[str, Decimal]:
    """Rebuild long-only quantities from cumulative broker fill reports.

    Alpaca fill quantities are cumulative per broker order, so only the positive delta from the
    previously applied cumulative quantity is reflected. This mirrors PortfolioReconciler without
    needing prices merely to perform a broker quantity guard.
    """

    quantities: dict[str, Decimal] = {}
    applied_by_order: dict[str, Decimal] = {}
    seen_reports: set[str] = set()

    for event in ledger.all_events():
        if event.event_type != "broker_execution_report":
            continue
        report = ExecutionReport.model_validate(event.payload)
        if report.report_id in seen_reports:
            continue
        seen_reports.add(report.report_id)
        if report.status not in _FILL_STATES:
            continue

        previous = applied_by_order.get(report.broker_order_id, Decimal("0"))
        if report.fill_quantity < previous:
            raise ValueError("broker cumulative fill quantity regressed")
        delta = report.fill_quantity - previous
        applied_by_order[report.broker_order_id] = report.fill_quantity
        if delta == 0:
            continue

        current = quantities.get(report.symbol, Decimal("0"))
        if report.side == OrderSide.BUY:
            current += delta
        else:
            current -= delta
        if current < 0:
            raise ValueError("runtime ledger replay would create a short position")
        if current == 0:
            quantities.pop(report.symbol, None)
        else:
            quantities[report.symbol] = current

    return quantities
