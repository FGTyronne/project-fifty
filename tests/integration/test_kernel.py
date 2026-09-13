from __future__ import annotations

from decimal import Decimal

from project_fifty.brokers.simulated.broker import SimulatedBroker
from project_fifty.control.state import ControlState
from project_fifty.domain.models import TradeAction
from project_fifty.execution.kernel import ExecutionKernel
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.risk.engine import RiskEngine
from tests.conftest import make_proposal


class CountingBroker(SimulatedBroker):
    def __init__(self) -> None:
        super().__init__(starting_cash_gbp=Decimal("50"))
        self.submit_calls = 0

    def submit(self, intent):  # type: ignore[override]
        self.submit_calls += 1
        return super().submit(intent)


def test_rejected_proposal_never_invokes_broker(settings: object) -> None:
    broker = CountingBroker()
    kernel = ExecutionKernel(
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=LocalAppendOnlyLedger(),
        control=ControlState(),
    )
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


def test_idempotency_key_cannot_create_two_fills(settings: object, control: ControlState) -> None:
    broker = SimulatedBroker(starting_cash_gbp=Decimal("50"))
    kernel = ExecutionKernel(
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=LocalAppendOnlyLedger(),
        control=control,
    )

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
    assert r2 is None


def test_valid_small_purchase_executes_and_updates_state(
    settings: object,
    control: ControlState,
) -> None:
    broker = SimulatedBroker(
        starting_cash_gbp=Decimal("50"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    kernel = ExecutionKernel(
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=LocalAppendOnlyLedger(),
        control=control,
    )
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
    assert portfolio.cash_gbp == Decimal("42.5")
    assert portfolio.positions["TEST"].quantity == Decimal("1")


def test_valid_reduction_and_exit_executes_autonomously(
    settings: object,
    control: ControlState,
) -> None:
    broker = SimulatedBroker(
        starting_cash_gbp=Decimal("50"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    kernel = ExecutionKernel(
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=LocalAppendOnlyLedger(),
        control=control,
    )

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


def test_unknown_state_does_not_resubmit(settings: object, control: ControlState) -> None:
    broker = SimulatedBroker(starting_cash_gbp=Decimal("50"), fail_with_unknown=True)
    kernel = ExecutionKernel(
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=LocalAppendOnlyLedger(),
        control=control,
    )

    proposal = make_proposal(
        proposal_id="unknown",
        key="unknown-key",
        action=TradeAction.BUY,
        qty=Decimal("1"),
        price=Decimal("5"),
    )
    _, report = kernel.handle_proposal(proposal)
    open_orders = broker.get_open_orders()

    assert report is not None
    assert report.status.value == "UNKNOWN"
    assert len(open_orders) == 1


def test_demo_flow_hold_buy_reduce_exit(settings: object, control: ControlState) -> None:
    ledger = LocalAppendOnlyLedger()
    broker = SimulatedBroker(
        starting_cash_gbp=Decimal("50"),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    kernel = ExecutionKernel(
        risk_engine=RiskEngine(settings),
        broker=broker,
        ledger=ledger,
        control=control,
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
    assert final_portfolio.nav_gbp == final_portfolio.cash_gbp
    assert final_portfolio.cash_gbp == Decimal("50.0")
    assert len(events) > 0
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
