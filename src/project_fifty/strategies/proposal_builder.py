from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

from project_fifty.domain.models import PortfolioState, TradeAction, TradeProposal
from project_fifty.strategies.contracts import StrategyContext, TargetPortfolio
from project_fifty.strategies.rebalance import EconomicRebalancePolicy, RebalancePlan


class ProposalBuilder:
    """Convert strategy target weights into Project Fifty TradeProposal objects.

    The builder uses Project Fifty's internally authorised portfolio state. Broker cash,
    equity and buying power are deliberately absent from this interface. When an economic
    rebalance policy is supplied, the same deterministic trade/no-trade plan can also be used by
    historical replay so validation and future autonomous execution share the same economics.
    """

    def __init__(
        self,
        *,
        min_order_notional: Decimal = Decimal("1.00"),
        estimated_fee: Decimal = Decimal("0"),
        estimated_slippage_rate: Decimal = Decimal("0.001"),
        rebalance_policy: EconomicRebalancePolicy | None = None,
    ) -> None:
        if not min_order_notional.is_finite() or min_order_notional < 0:
            raise ValueError("min_order_notional must be finite and non-negative")
        if not estimated_fee.is_finite() or estimated_fee < 0:
            raise ValueError("estimated_fee must be finite and non-negative")
        if (
            not estimated_slippage_rate.is_finite()
            or estimated_slippage_rate < 0
            or estimated_slippage_rate >= 1
        ):
            raise ValueError("estimated_slippage_rate must be in [0, 1)")
        self._min_order_notional = min_order_notional
        self._estimated_fee = estimated_fee
        self._estimated_slippage_rate = estimated_slippage_rate
        self._rebalance_policy = rebalance_policy

    def build(
        self,
        *,
        target: TargetPortfolio,
        context: StrategyContext,
    ) -> list[TradeProposal]:
        proposals, _ = self.build_with_plan(target=target, context=context)
        return proposals

    def build_with_plan(
        self,
        *,
        target: TargetPortfolio,
        context: StrategyContext,
    ) -> tuple[list[TradeProposal], RebalancePlan | None]:
        self._validate_target_context(target, context)
        portfolio = context.portfolio
        plan = (
            self._rebalance_policy.plan(target=target, context=context)
            if self._rebalance_policy is not None
            else None
        )

        proposals: list[TradeProposal] = []
        symbols = sorted(set(portfolio.positions) | set(target.weights))

        for symbol in symbols:
            instruction = plan.for_symbol(symbol) if plan is not None else None
            if instruction is not None and not instruction.execute:
                continue

            price = context.reference_prices.get(symbol)
            timestamp = context.reference_price_timestamps.get(symbol)
            if price is None or timestamp is None:
                raise ValueError(f"missing reference price or timestamp for {symbol}")

            current_position = portfolio.positions.get(symbol)
            current_quantity = (
                current_position.quantity if current_position is not None else Decimal("0")
            )
            current_notional = current_quantity * price
            target_weight = target.weights.get(symbol, Decimal("0"))
            target_notional = portfolio.nav * target_weight
            delta_notional = target_notional - current_notional
            full_exit = current_quantity > 0 and target_weight == 0

            # Full exits are risk-reducing and may bypass the economic/minimum-order no-trade band.
            if full_exit:
                proposals.append(
                    self._proposal(
                        target=target,
                        symbol=symbol,
                        action=TradeAction.EXIT,
                        quantity=None,
                        reduce_fraction=None,
                        estimated_notional=current_notional,
                        reference_price=price,
                        reference_timestamp=timestamp,
                        ordinal=len(proposals),
                    )
                )
                continue

            if abs(delta_notional) < self._min_order_notional:
                continue

            if delta_notional > 0:
                quantity = delta_notional / price
                proposals.append(
                    self._proposal(
                        target=target,
                        symbol=symbol,
                        action=TradeAction.BUY if current_quantity == 0 else TradeAction.ADD,
                        quantity=quantity,
                        reduce_fraction=None,
                        estimated_notional=delta_notional,
                        reference_price=price,
                        reference_timestamp=timestamp,
                        ordinal=len(proposals),
                    )
                )
                continue

            if current_quantity <= 0:
                continue

            reduction_notional = -delta_notional
            reduction_quantity = min(reduction_notional / price, current_quantity)
            reduce_fraction = reduction_quantity / current_quantity
            proposals.append(
                self._proposal(
                    target=target,
                    symbol=symbol,
                    action=TradeAction.REDUCE,
                    quantity=None,
                    reduce_fraction=reduce_fraction,
                    estimated_notional=reduction_quantity * price,
                    reference_price=price,
                    reference_timestamp=timestamp,
                    ordinal=len(proposals),
                )
            )

        # Reductions and exits free constitutional cash before any new exposure is considered.
        priority = {
            TradeAction.EXIT: 0,
            TradeAction.REDUCE: 1,
            TradeAction.BUY: 2,
            TradeAction.ADD: 2,
        }
        return (
            sorted(proposals, key=lambda proposal: (priority[proposal.action], proposal.symbol)),
            plan,
        )

    def _proposal(
        self,
        *,
        target: TargetPortfolio,
        symbol: str,
        action: TradeAction,
        quantity: Decimal | None,
        reduce_fraction: Decimal | None,
        estimated_notional: Decimal,
        reference_price: Decimal,
        reference_timestamp: datetime,
        ordinal: int,
    ) -> TradeProposal:
        estimated_slippage = estimated_notional * self._estimated_slippage_rate
        identity = (
            f"{target.strategy_id}|{target.strategy_version}|{target.market_state_hash}|"
            f"{symbol}|{action.value}|{ordinal}"
        )
        digest = sha256(identity.encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC)
        return TradeProposal(
            proposal_id=f"strategy-{digest[:24]}",
            idempotency_key=f"strategy-{digest}",
            symbol=symbol,
            action=action,
            quantity=quantity,
            notional=quantity * reference_price if quantity is not None else None,
            reduce_fraction=reduce_fraction,
            reference_price=reference_price,
            reference_price_timestamp=reference_timestamp,
            estimated_fee=self._estimated_fee,
            estimated_slippage=estimated_slippage,
            quote_currency=target.currency,
            created_at=created_at,
        )

    @staticmethod
    def _validate_target_context(target: TargetPortfolio, context: StrategyContext) -> None:
        if target.currency != context.currency:
            raise ValueError("target currency must match strategy context currency")
        if target.market_state_hash != context.market_state_hash:
            raise ValueError("target was not generated from the current market state")
        if target.as_of != context.as_of:
            raise ValueError("target timestamp must match strategy context timestamp")
        ProposalBuilder._validate_portfolio(context.portfolio)

    @staticmethod
    def _validate_portfolio(portfolio: PortfolioState) -> None:
        if not portfolio.nav.is_finite() or portfolio.nav < 0:
            raise ValueError("portfolio NAV must be finite and non-negative")
