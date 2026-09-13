from datetime import UTC, datetime
from decimal import Decimal

from project_fifty.domain.models import PortfolioState, Position, TradeAction
from project_fifty.strategies.contracts import StrategyContext, TargetPortfolio
from project_fifty.strategies.proposal_builder import ProposalBuilder
from project_fifty.strategies.rebalance import (
    EconomicRebalanceConfig,
    EconomicRebalancePolicy,
    RebalanceReason,
)


def _context(*, cash: str, quantity: str = "0") -> StrategyContext:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    positions = {}
    qty = Decimal(quantity)
    if qty > 0:
        positions["AAPL"] = Position(
            symbol="AAPL",
            quantity=qty,
            average_price=Decimal("100"),
        )
    position_value = qty * Decimal("100")
    nav = Decimal(cash) + position_value
    return StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=Decimal(cash),
            positions=positions,
            nav=nav,
            currency="USD",
            as_of=as_of,
        ),
        reference_prices={"AAPL": Decimal("100")},
        reference_price_timestamps={"AAPL": as_of},
        market_state_hash="m5-state",
    )


def _target(context: StrategyContext, weight: str) -> TargetPortfolio:
    target_weight = Decimal(weight)
    return TargetPortfolio(
        as_of=context.as_of,
        currency="USD",
        weights={"AAPL": target_weight} if target_weight > 0 else {},
        cash_weight=Decimal("1") - target_weight,
        strategy_id="test",
        strategy_version="1",
        confidence=Decimal("0.5"),
        market_state_hash=context.market_state_hash,
    )


def test_small_rebalance_is_suppressed_by_nav_band() -> None:
    context = _context(cash="45", quantity="0.05")  # NAV 50, current weight 10%
    policy = EconomicRebalancePolicy()

    plan = policy.plan(target=_target(context, "0.12"), context=context)
    instruction = plan.for_symbol("AAPL")

    assert plan.threshold_notional == Decimal("3.750")
    assert instruction is not None
    assert instruction.execute is False
    assert instruction.reason == RebalanceReason.BELOW_ECONOMIC_THRESHOLD


def test_material_rebalance_is_allowed() -> None:
    context = _context(cash="45", quantity="0.05")
    policy = EconomicRebalancePolicy()

    plan = policy.plan(target=_target(context, "0.30"), context=context)
    instruction = plan.for_symbol("AAPL")

    assert instruction is not None
    assert instruction.execute is True
    assert instruction.reason == RebalanceReason.EXECUTE


def test_full_exit_bypasses_economic_band() -> None:
    context = _context(cash="49", quantity="0.01")  # $1 position, below $3.75 band
    policy = EconomicRebalancePolicy()

    plan = policy.plan(target=_target(context, "0"), context=context)
    instruction = plan.for_symbol("AAPL")

    assert instruction is not None
    assert instruction.execute is True
    assert instruction.risk_reducing is True
    assert instruction.reason == RebalanceReason.FORCED_EXIT


def test_proposal_builder_uses_same_policy_and_keeps_forced_exit() -> None:
    policy = EconomicRebalancePolicy(
        EconomicRebalanceConfig(
            minimum_trade_notional=Decimal("2"),
            minimum_trade_fraction_of_nav=Decimal("0.075"),
        )
    )
    small_context = _context(cash="45", quantity="0.05")
    builder = ProposalBuilder(rebalance_policy=policy)

    proposals, plan = builder.build_with_plan(
        target=_target(small_context, "0.12"),
        context=small_context,
    )
    assert proposals == []
    assert plan is not None
    assert len(plan.suppressed) == 1

    exit_context = _context(cash="49", quantity="0.01")
    proposals, _ = builder.build_with_plan(
        target=_target(exit_context, "0"),
        context=exit_context,
    )
    assert len(proposals) == 1
    assert proposals[0].action == TradeAction.EXIT
