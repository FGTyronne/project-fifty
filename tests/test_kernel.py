from hypothesis import given, strategies as st

from project_fifty import (
    Action,
    AppendOnlyLedger,
    AutonomousTradingKernel,
    ExecutionStatus,
    KillSwitchState,
    PortfolioState,
    RiskEngine,
    SimulatedBroker,
    TradeProposal,
)


def build_kernel(price: float = 10.0, kill_switch: KillSwitchState | None = None) -> AutonomousTradingKernel:
    return AutonomousTradingKernel(
        risk_engine=RiskEngine(),
        broker=SimulatedBroker({"ABC": price}),
        ledger=AppendOnlyLedger(),
        kill_switch=kill_switch,
    )


def test_buy_rejected_when_insufficient_cash() -> None:
    kernel = build_kernel(price=50.0)
    portfolio = PortfolioState(cash=20.0, positions={})

    proposal = TradeProposal("p1", "ABC", Action.BUY, quantity=1)
    report, next_portfolio = kernel.process_proposal(proposal, portfolio)

    assert report.status == ExecutionStatus.REJECTED
    assert "insufficient cash" in report.message
    assert next_portfolio == portfolio


def test_sell_rejected_when_insufficient_position() -> None:
    kernel = build_kernel(price=50.0)
    portfolio = PortfolioState(cash=200.0, positions={"ABC": 1})

    proposal = TradeProposal("p2", "ABC", Action.SELL, quantity=2)
    report, next_portfolio = kernel.process_proposal(proposal, portfolio)

    assert report.status == ExecutionStatus.REJECTED
    assert "insufficient position" in report.message
    assert next_portfolio == portfolio


def test_kill_switch_blocks_risk_actions_but_allows_cancel() -> None:
    kernel = build_kernel(kill_switch=KillSwitchState(tripped=True, reason="manual stop"))
    portfolio = PortfolioState(cash=100.0, positions={"ABC": 1})

    blocked_report, _ = kernel.process_proposal(
        TradeProposal("p3", "ABC", Action.BUY, quantity=1), portfolio
    )
    allowed_report, _ = kernel.process_proposal(
        TradeProposal("p4", "ABC", Action.CANCEL), portfolio
    )

    assert blocked_report.status == ExecutionStatus.REJECTED
    assert "kill switch" in blocked_report.message
    assert allowed_report.status == ExecutionStatus.CANCELLED


def test_broker_fills_buy_and_sell() -> None:
    kernel = build_kernel(price=25.0)
    portfolio = PortfolioState(cash=500.0, positions={})

    buy_report, portfolio = kernel.process_proposal(
        TradeProposal("p5", "ABC", Action.BUY, quantity=4), portfolio
    )
    sell_report, portfolio = kernel.process_proposal(
        TradeProposal("p6", "ABC", Action.SELL, quantity=2), portfolio
    )

    assert buy_report.status == ExecutionStatus.FILLED
    assert sell_report.status == ExecutionStatus.FILLED
    assert portfolio.cash == 450.0
    assert portfolio.positions["ABC"] == 2


def test_ledger_is_append_only_sequence() -> None:
    ledger = AppendOnlyLedger()
    ledger.append("a", {"v": 1})
    snapshot = ledger.entries
    ledger.append("b", {"v": 2})

    assert [e.sequence for e in ledger.entries] == [1, 2]
    assert len(snapshot) == 1


proposal_action_strategy = st.sampled_from(list(Action))
proposal_qty_strategy = st.integers(min_value=0, max_value=5)
price_strategy = st.floats(min_value=1.0, max_value=200.0, allow_nan=False, allow_infinity=False)


@given(
    actions=st.lists(proposal_action_strategy, min_size=1, max_size=40),
    quantities=st.lists(proposal_qty_strategy, min_size=1, max_size=40),
    prices=st.lists(price_strategy, min_size=1, max_size=40),
)
def test_invariants_no_negative_cash_or_positions(actions, quantities, prices) -> None:
    portfolio = PortfolioState(cash=10_000.0, positions={})

    for i, action in enumerate(actions):
        quantity = quantities[i % len(quantities)]
        price = float(prices[i % len(prices)])
        kernel = build_kernel(price=price)

        if action in {Action.BUY, Action.SELL, Action.REDUCE, Action.ADD}:
            quantity = max(1, quantity)
        else:
            quantity = 0

        proposal = TradeProposal(
            proposal_id=f"prop-{i}",
            symbol="ABC",
            action=action,
            quantity=quantity,
        )
        _, portfolio = kernel.process_proposal(proposal, portfolio)

        assert portfolio.cash >= 0
        assert all(qty >= 0 for qty in portfolio.positions.values())
