from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from project_fifty.domain.models import ExecutionReport, OrderSide, OrderStatus
from project_fifty.portfolio.reconcile import PortfolioReconciler


def make_fill(
    *,
    report_id: str,
    side: OrderSide,
    qty: str,
    price: str,
    fee: str = "0.01",
) -> ExecutionReport:
    return ExecutionReport(
        report_id=report_id,
        broker_order_id=str(uuid4()),
        idempotency_key=report_id,
        symbol="TEST",
        side=side,
        status=OrderStatus.FILLED,
        fill_quantity=Decimal(qty),
        fill_price=Decimal(price),
        fee=Decimal(fee),
        slippage=Decimal("0"),
        currency="USD",
    )


def test_replay_duplicate_events_do_not_corrupt_state() -> None:
    buy = make_fill(report_id="r1", side=OrderSide.BUY, qty="1", price="7.5")
    sell = make_fill(report_id="r2", side=OrderSide.SELL, qty="1", price="7.5")
    replayed = PortfolioReconciler.replay_events(
        starting_cash=Decimal("50"),
        events=[buy, buy, sell, sell],
        mark_prices={"TEST": Decimal("7.5")},
        currency="USD",
    )
    assert replayed.positions == {}
    assert replayed.cash == Decimal("49.98")


def test_fees_and_slippage_reduce_nav_correctly() -> None:
    buy = make_fill(report_id="r1", side=OrderSide.BUY, qty="1", price="10", fee="0.20")
    replayed = PortfolioReconciler.replay_events(
        starting_cash=Decimal("50"),
        events=[buy],
        mark_prices={"TEST": Decimal("9.5")},
        currency="USD",
    )
    assert replayed.nav == Decimal("49.30")
