from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from project_fifty.brokers.simulated.broker import SimulatedBroker
from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
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


class CountingBroker(SimulatedBroker):
    def __init__(self, *, starting_cash: Decimal, fail_with_unknown: bool = False) -> None:
        super().__init__(starting_cash=starting_cash, fail_with_unknown=fail_with_unknown)
        self.submit_calls = 0

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        self.submit_calls += 1
        return super().submit(intent)


def _kernel(
    *,
    settings: Settings,
    broker: SimulatedBroker,
    control: ControlState | None = None,
    ledger_path: Path | None = None,
) -> ExecutionKernel:
    return ExecutionKernel(
        settings=settings,
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=LocalAppendOnlyLedger(ledger_path),
        control=control or ControlState(),
    )


def test_rejected_proposal_never_invokes_broker(settings: Settings) -> None:
    broker = CountingBroker(starting_cash=Decimal("100000"))
    kernel = _kernel(settings=settings, broker=broker)

    proposal = make_proposal(
        proposal_id="reject",
        key="reject-key",
        action=TradeAction.BUY,
        qty=Decimal("100"),
        price=Decimal("10"),
        notional=Decimal("1000"),
    )
    decision, report = kernel.handle_proposal(proposal)

    assert decision.approved is False
    assert report is None
    assert broker.submit_calls == 0


def test_notional_cannot_understate_executable_quantity(settings: Settings) -> None:
    broker = SimulatedBroker(starting_cash=Decimal("100000"))
    kernel = _kernel(settings=settings, broker=broker)

    proposal = make_proposal(
        proposal_id="mismatch",
        key="mismatch-key",
        action=TradeAction.BUY,
        qty=Decimal("10"),
        price=Decimal("10"),
        notional=Decimal("1"),
    )
    decision, report = kernel.handle_proposal(proposal)

    assert decision.approved is False
    assert decision.reason == RejectionReason.NOTIONAL_QUANTITY_MISMATCH
    assert report is None


def test_broker_buying_power_cannot_expand_authority(settings: Settings) -> None:
    broker = SimulatedBroker(
        starting_cash=Decimal("100000"),
        reported_buying_power=Decimal("400000"),
    )
    kernel = _kernel(settings=settings, broker=broker)

    first = make_proposal(
        proposal_id="buy-1",
        key="buy-1",
        action=TradeAction.BUY,
        qty=Decimal("3"),
        price=Decimal("10"),
        notional=Decimal("30"),
    )
    second = make_proposal(
        proposal_id="buy-2",
        key="buy-2",
        action=TradeAction.BUY,
        qty=Decimal("3"),
        price=Decimal("10"),
        notional=Decimal("30"),
    )

    d1, _ = kernel.handle_proposal(first)
    d2, _ = kernel.handle_proposal(second)

    assert d1.approved is True
    assert d2.approved is False
    assert d2.reason == RejectionReason.INSUFFICIENT_CASH


def test_currency_mismatch_rejected(settings: Settings) -> None:
    broker = SimulatedBroker(starting_cash=Decimal("50"), currency="USD")
    kernel = _kernel(settings=settings, broker=broker)

    proposal = make_proposal(
        proposal_id="fx-mismatch",
        key="fx-mismatch",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
        currency="GBP",
    )
    decision, report = kernel.handle_proposal(proposal)

    assert decision.approved is False
    assert decision.reason == RejectionReason.CURRENCY_MISMATCH
    assert report is None


def test_idempotency_key_cannot_create_two_fills(
    settings: Settings,
    control: ControlState,
) -> None:
    broker = SimulatedBroker(starting_cash=Decimal("50"))
    kernel = _kernel(settings=settings, broker=broker, control=control)

    proposal = make_proposal(
        proposal_id="id-1",
        key="same-key",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
    )
    d1, r1 = kernel.handle_proposal(proposal)
    d2, r2 = kernel.handle_proposal(proposal)

    assert d1.approved is True
    assert r1 is not None
    assert d2.approved is False
    assert d2.reason == RejectionReason.DUPLICATE_IDEMPOTENCY_KEY
    assert r2 is None


def test_restart_cannot_duplicate_ambiguous_order(settings: Settings, tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    broker = CountingBroker(starting_cash=Decimal("50"), fail_with_unknown=True)
    kernel1 = _kernel(settings=settings, broker=broker, ledger_path=ledger_path)

    proposal = make_proposal(
        proposal_id="unknown",
        key="unknown-key",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
    )
    d1, r1 = kernel1.handle_proposal(proposal)
    assert d1.approved is True
    assert r1 is not None
    assert r1.status == OrderStatus.UNKNOWN
    assert broker.submit_calls == 1

    restarted_broker = CountingBroker(starting_cash=Decimal("50"), fail_with_unknown=True)
    kernel2 = _kernel(settings=settings, broker=restarted_broker, ledger_path=ledger_path)
    d2, r2 = kernel2.handle_proposal(proposal)

    assert d2.approved is False
    assert d2.reason == RejectionReason.DUPLICATE_IDEMPOTENCY_KEY
    assert r2 is None
    assert restarted_broker.submit_calls == 0


def test_valid_small_purchase_executes_and_updates_state(settings: Settings) -> None:
    broker = SimulatedBroker(
        starting_cash=Decimal("50"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    kernel = _kernel(settings=settings, broker=broker)
    proposal = make_proposal(
        proposal_id="buy1",
        key="buy1-key",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("7.5"),
        notional=Decimal("7.5"),
    )
    decision, report = kernel.handle_proposal(proposal)
    portfolio = broker.get_portfolio()

    assert decision.approved is True
    assert report is not None
    assert portfolio.cash == Decimal("42.5")
    assert portfolio.positions["TEST"].quantity == Decimal("1")


def test_cancel_executes_end_to_end(settings: Settings) -> None:
    broker = SimulatedBroker(starting_cash=Decimal("50"), fail_with_unknown=True)
    kernel = _kernel(settings=settings, broker=broker)

    buy = make_proposal(
        proposal_id="buy",
        key="buy-key",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
    )
    _, unknown_report = kernel.handle_proposal(buy)
    assert unknown_report is not None

    cancel = make_proposal(
        proposal_id="cancel",
        key="cancel-key",
        action=TradeAction.CANCEL,
        qty=None,
        price=Decimal("5"),
        cancel_order_id=unknown_report.broker_order_id,
    )
    decision, cancel_report = kernel.handle_proposal(cancel)

    assert decision.approved is True
    assert cancel_report is not None
    assert cancel_report.status == OrderStatus.CANCELLED
    assert len(broker.get_open_orders()) == 0


def test_valid_reduction_and_exit_executes_autonomously(settings: Settings) -> None:
    broker = SimulatedBroker(
        starting_cash=Decimal("50"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    kernel = _kernel(settings=settings, broker=broker)

    buy = make_proposal(
        proposal_id="buy",
        key="buy-key",
        action=TradeAction.BUY,
        qty=Decimal("2"),
        price=Decimal("5"),
    )
    reduce = make_proposal(
        proposal_id="reduce",
        key="reduce-key",
        action=TradeAction.REDUCE,
        qty=None,
        price=Decimal("5"),
        reduce_fraction=Decimal("0.4"),
    )
    exit_all = make_proposal(
        proposal_id="exit",
        key="exit-key",
        action=TradeAction.EXIT,
        qty=None,
        price=Decimal("5"),
    )

    kernel.handle_proposal(buy)
    _, r2 = kernel.handle_proposal(reduce)
    _, r3 = kernel.handle_proposal(exit_all)

    assert r2 is not None
    assert r3 is not None
    assert broker.get_portfolio().positions == {}


def test_demo_flow_hold_buy_reduce_exit(settings: Settings) -> None:
    ledger = LocalAppendOnlyLedger()
    broker = SimulatedBroker(
        starting_cash=Decimal("50"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    kernel = ExecutionKernel(
        settings=settings,
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=ledger,
        control=ControlState(),
    )

    hold = make_proposal(
        proposal_id="d-hold",
        key="d-hold",
        action=TradeAction.HOLD,
        qty=None,
        price=Decimal("7.5"),
    )
    buy = make_proposal(
        proposal_id="d-buy",
        key="d-buy",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("7.5"),
        notional=Decimal("7.5"),
    )
    reduce = make_proposal(
        proposal_id="d-reduce",
        key="d-reduce",
        action=TradeAction.REDUCE,
        qty=None,
        price=Decimal("7.5"),
        reduce_fraction=Decimal("0.4"),
    )
    exit_all = make_proposal(
        proposal_id="d-exit",
        key="d-exit",
        action=TradeAction.EXIT,
        qty=None,
        price=Decimal("7.5"),
    )

    kernel.handle_proposal(hold)
    kernel.handle_proposal(buy)
    kernel.handle_proposal(reduce)
    kernel.handle_proposal(exit_all)

    final_portfolio = broker.get_portfolio()
    events = ledger.all_events()

    assert final_portfolio.positions == {}
    assert final_portfolio.nav == final_portfolio.cash
    assert final_portfolio.cash == Decimal("50.0")
    assert len(events) > 0
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
