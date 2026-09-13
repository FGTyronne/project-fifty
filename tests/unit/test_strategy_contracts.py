from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from project_fifty.domain.models import PortfolioState, Position, TradeAction
from project_fifty.strategies.contracts import StrategyContext, TargetPortfolio
from project_fifty.strategies.proposal_builder import ProposalBuilder


def _context(
    *,
    cash: Decimal = Decimal("67.6725"),
    nav: Decimal = Decimal("67.6725"),
    positions: dict[str, Position] | None = None,
    prices: dict[str, Decimal] | None = None,
) -> StrategyContext:
    as_of = datetime(2026, 9, 14, 14, 35, tzinfo=UTC)
    reference_prices = prices or {"AAPL": Decimal("100")}
    return StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=cash,
            positions=positions or {},
            nav=nav,
            currency="USD",
            as_of=as_of,
        ),
        reference_prices=reference_prices,
        reference_price_timestamps={symbol: as_of for symbol in reference_prices},
        market_state_hash="market-1",
    )


def _target(
    context: StrategyContext,
    *,
    weights: dict[str, Decimal],
    cash_weight: Decimal,
) -> TargetPortfolio:
    return TargetPortfolio(
        as_of=context.as_of,
        currency="USD",
        weights=weights,
        cash_weight=cash_weight,
        strategy_id="hybrid-baseline",
        strategy_version="1",
        confidence=Decimal("0.65"),
        market_state_hash=context.market_state_hash,
        evidence={"regime": "risk_on"},
    )


def test_target_portfolio_requires_exact_total_weight() -> None:
    context = _context()

    with pytest.raises(ValidationError):
        _target(
            context,
            weights={"AAPL": Decimal("0.50")},
            cash_weight=Decimal("0.49"),
        )


def test_builder_uses_internal_nav_to_size_initial_buy() -> None:
    context = _context()
    target = _target(
        context,
        weights={"AAPL": Decimal("0.50")},
        cash_weight=Decimal("0.50"),
    )

    proposals = ProposalBuilder(min_order_notional=Decimal("1")).build(
        target=target,
        context=context,
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.action == TradeAction.BUY
    assert proposal.quantity == Decimal("0.3383625")
    assert proposal.notional == Decimal("33.8362500")
    assert proposal.quote_currency == "USD"


def test_reductions_are_emitted_before_new_exposure() -> None:
    context = _context(
        cash=Decimal("27.6725"),
        nav=Decimal("67.6725"),
        positions={
            "AAPL": Position(
                symbol="AAPL",
                quantity=Decimal("0.4"),
                average_price=Decimal("100"),
            )
        },
        prices={"AAPL": Decimal("100"), "MSFT": Decimal("200")},
    )
    target = _target(
        context,
        weights={"MSFT": Decimal("0.50")},
        cash_weight=Decimal("0.50"),
    )

    proposals = ProposalBuilder(min_order_notional=Decimal("1")).build(
        target=target,
        context=context,
    )

    assert [proposal.action for proposal in proposals] == [TradeAction.EXIT, TradeAction.BUY]
    assert [proposal.symbol for proposal in proposals] == ["AAPL", "MSFT"]


def test_builder_rejects_target_from_different_market_state() -> None:
    context = _context()
    target = TargetPortfolio(
        as_of=context.as_of,
        currency="USD",
        weights={},
        cash_weight=Decimal("1"),
        strategy_id="hybrid-baseline",
        strategy_version="1",
        confidence=Decimal("0.2"),
        market_state_hash="stale-market",
    )

    with pytest.raises(ValueError, match="current market state"):
        ProposalBuilder().build(target=target, context=context)


def test_context_rejects_currency_mismatch() -> None:
    as_of = datetime(2026, 9, 14, 14, 35, tzinfo=UTC)

    with pytest.raises(ValidationError):
        StrategyContext(
            as_of=as_of,
            currency="GBP",
            portfolio=PortfolioState(
                cash=Decimal("50"),
                positions={},
                nav=Decimal("50"),
                currency="USD",
                as_of=as_of,
            ),
            reference_prices={"AAPL": Decimal("100")},
            reference_price_timestamps={"AAPL": as_of},
            market_state_hash="market-1",
        )
