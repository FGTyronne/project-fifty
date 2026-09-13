from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.domain.models import ExecutionReport, OrderSide, OrderStatus
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.session.observation import calculate_forward_metrics


def _snapshot(
    ledger: LocalAppendOnlyLedger,
    *,
    as_of: datetime,
    bar: datetime,
    nav: str,
    spy: str,
    positioned: bool,
) -> None:
    ledger.append(
        "forward_observation_snapshot",
        {
            "as_of": as_of.isoformat(),
            "decision_bar_time": bar.isoformat(),
            "nav": nav,
            "cash": "0" if positioned else nav,
            "position_quantities": {"SPY": "0.1"} if positioned else {},
            "spy_mark": spy,
            "spy_quote_time": as_of.isoformat(),
            "currency": "USD",
        },
    )


def _report(
    *,
    report_id: str,
    status: OrderStatus,
    qty: str,
    fill_price: str,
    slippage: str,
) -> ExecutionReport:
    return ExecutionReport(
        report_id=report_id,
        broker_order_id="broker-1",
        idempotency_key="logical-1",
        symbol="SPY",
        side=OrderSide.BUY,
        status=status,
        fill_quantity=Decimal(qty),
        fill_price=Decimal(fill_price),
        fee=Decimal("0"),
        slippage=Decimal(slippage),
        currency="USD",
    )


def test_forward_metrics_compare_project_cash_and_spy_and_apply_cumulative_fills() -> None:
    ledger = LocalAppendOnlyLedger()
    start = datetime(2026, 9, 14, 15, 5, tzinfo=UTC)
    _snapshot(
        ledger,
        as_of=start,
        bar=start - timedelta(days=1),
        nav="100",
        spy="500",
        positioned=False,
    )
    _snapshot(
        ledger,
        as_of=start + timedelta(days=1),
        bar=start,
        nav="90",
        spy="550",
        positioned=True,
    )
    partial = _report(
        report_id="partial",
        status=OrderStatus.PARTIALLY_FILLED,
        qty="0.05",
        fill_price="500",
        slippage="0.10",
    )
    filled = _report(
        report_id="filled",
        status=OrderStatus.FILLED,
        qty="0.10",
        fill_price="510",
        slippage="0.20",
    )
    ledger.append("broker_execution_report", partial.model_dump(mode="json"))
    ledger.append("broker_execution_report", filled.model_dump(mode="json"))

    metrics = calculate_forward_metrics(
        events=ledger.all_events(),
        starting_nav=Decimal("100"),
        generated_at=start + timedelta(days=56),
    )

    assert metrics.sessions == 2
    assert metrics.current_nav == Decimal("90")
    assert metrics.project_return == Decimal("-0.1")
    assert metrics.cash_return == Decimal("0")
    assert metrics.spy_buy_hold_return == Decimal("0.1")
    assert metrics.max_drawdown == Decimal("-0.1")
    assert metrics.turnover_notional == Decimal("51.0")
    assert metrics.turnover_ratio == Decimal("0.51")
    assert metrics.observed_slippage == Decimal("0.20")
    assert metrics.filled_orders == 1
    assert metrics.cash_sessions == 1
    assert metrics.cash_session_fraction == Decimal("0.5")
    assert metrics.session_gate_met is False
    assert metrics.calendar_gate_met is True
    assert metrics.extended_time_gate_met is False


def test_duplicate_decision_bar_does_not_inflate_session_count() -> None:
    ledger = LocalAppendOnlyLedger()
    start = datetime(2026, 9, 14, 15, 5, tzinfo=UTC)
    bar = start - timedelta(days=1)
    _snapshot(ledger, as_of=start, bar=bar, nav="100", spy="500", positioned=False)
    _snapshot(
        ledger,
        as_of=start + timedelta(minutes=1),
        bar=bar,
        nav="101",
        spy="501",
        positioned=False,
    )

    metrics = calculate_forward_metrics(
        events=ledger.all_events(),
        starting_nav=Decimal("100"),
        generated_at=start + timedelta(days=1),
    )

    assert metrics.sessions == 1
    assert metrics.current_nav == Decimal("101")
    assert metrics.spy_buy_hold_return == Decimal("0")


def test_empty_observation_sample_omits_statistical_returns() -> None:
    metrics = calculate_forward_metrics(
        events=[],
        starting_nav=Decimal("67.6725"),
        generated_at=datetime(2026, 9, 13, tzinfo=UTC),
    )

    assert metrics.sessions == 0
    assert metrics.current_nav is None
    assert metrics.project_return is None
    assert metrics.spy_buy_hold_return is None
    assert metrics.max_drawdown is None
    assert metrics.extended_time_gate_met is False
