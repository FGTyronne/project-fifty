from decimal import Decimal

from project_fifty.domain.models import ExecutionReport, OrderIntent, OrderSide, OrderStatus
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.session.runtime_state import expected_position_quantities, pending_orders


def _intent(*, key: str, intent_id: str, side: OrderSide = OrderSide.BUY) -> OrderIntent:
    return OrderIntent(
        intent_id=intent_id,
        idempotency_key=key,
        proposal_id=f"proposal-{key}",
        symbol="SPY",
        side=side,
        quantity=Decimal("0.1"),
        reference_price=Decimal("500"),
        notional=Decimal("50"),
        currency="USD",
    )


def _report(
    *,
    report_id: str,
    order_id: str,
    key: str,
    side: OrderSide,
    status: OrderStatus,
    quantity: str,
) -> ExecutionReport:
    return ExecutionReport(
        report_id=report_id,
        broker_order_id=order_id,
        idempotency_key=key,
        symbol="SPY",
        side=side,
        status=status,
        fill_quantity=Decimal(quantity),
        fill_price=Decimal("500"),
        fee=Decimal("0"),
        slippage=Decimal("0"),
        currency="USD",
    )


def test_pending_order_survives_restart_view_until_terminal() -> None:
    ledger = LocalAppendOnlyLedger()
    intent = _intent(key="buy-1", intent_id="intent-1")
    ledger.append("order_intent_created", intent.model_dump(mode="json"))
    ledger.append(
        "order_state_transition",
        {"order_id": intent.intent_id, "from": "CREATED", "to": "ACKNOWLEDGED"},
    )

    assert [item.idempotency_key for item in pending_orders(ledger)] == ["buy-1"]

    ledger.append(
        "order_state_transition",
        {"order_id": intent.intent_id, "from": "ACKNOWLEDGED", "to": "FILLED"},
    )
    assert pending_orders(ledger) == ()


def test_position_view_applies_only_cumulative_fill_deltas() -> None:
    ledger = LocalAppendOnlyLedger()
    partial = _report(
        report_id="partial",
        order_id="broker-1",
        key="buy-1",
        side=OrderSide.BUY,
        status=OrderStatus.PARTIALLY_FILLED,
        quantity="0.04",
    )
    filled = _report(
        report_id="filled",
        order_id="broker-1",
        key="buy-1",
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        quantity="0.10",
    )
    ledger.append("broker_execution_report", partial.model_dump(mode="json"))
    ledger.append("broker_execution_report", filled.model_dump(mode="json"))

    assert expected_position_quantities(ledger) == {"SPY": Decimal("0.10")}


def test_position_view_handles_full_exit_without_shorting() -> None:
    ledger = LocalAppendOnlyLedger()
    buy = _report(
        report_id="buy",
        order_id="broker-buy",
        key="buy-1",
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        quantity="0.10",
    )
    sell = _report(
        report_id="sell",
        order_id="broker-sell",
        key="sell-1",
        side=OrderSide.SELL,
        status=OrderStatus.FILLED,
        quantity="0.10",
    )
    ledger.append("broker_execution_report", buy.model_dump(mode="json"))
    ledger.append("broker_execution_report", sell.model_dump(mode="json"))

    assert expected_position_quantities(ledger) == {}
