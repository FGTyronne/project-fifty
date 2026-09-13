from datetime import UTC, datetime
from decimal import Decimal

from project_fifty.domain.models import PortfolioState, TradeAction
from project_fifty.strategies.contracts import StrategyContext, TargetPortfolio
from project_fifty.strategies.proposal_builder import ProposalBuilder


def test_full_allocation_initial_buy_reserves_estimated_slippage() -> None:
    as_of = datetime(2026, 9, 14, 14, 35, tzinfo=UTC)
    cash = Decimal("67.6725")
    price = Decimal("500")
    context = StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=cash,
            positions={},
            nav=cash,
            currency="USD",
            as_of=as_of,
        ),
        reference_prices={"SPY": price},
        reference_price_timestamps={"SPY": as_of},
        market_state_hash="m10-full-allocation",
        history={},
        benchmark_symbol="SPY",
    )
    target = TargetPortfolio(
        as_of=as_of,
        currency="USD",
        weights={"SPY": Decimal("1")},
        cash_weight=Decimal("0"),
        strategy_id="single-market-trend-baseline",
        strategy_version="6.0.0",
        confidence=Decimal("0.5"),
        market_state_hash=context.market_state_hash,
    )

    proposal = ProposalBuilder().build(target=target, context=context)[0]

    assert proposal.action == TradeAction.BUY
    assert proposal.notional is not None
    assert proposal.notional < cash
    assert proposal.notional + proposal.estimated_fee + proposal.estimated_slippage == cash
    assert proposal.quantity == proposal.notional / price
