from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from project_fifty.strategies.contracts import StrategyContext, TargetPortfolio

_ZERO = Decimal("0")
_ONE = Decimal("1")


class RebalanceReason(str, Enum):
    EXECUTE = "EXECUTE"
    FORCED_EXIT = "FORCED_EXIT"
    BELOW_ECONOMIC_THRESHOLD = "BELOW_ECONOMIC_THRESHOLD"
    NO_CHANGE = "NO_CHANGE"


@dataclass(frozen=True)
class EconomicRebalanceConfig:
    """Economic trading threshold shared by replay and autonomous execution.

    These limits decide whether a desired strategy rebalance is economically worth attempting.
    They do not expand constitutional risk authority and are not a replacement for RiskEngine.
    """

    minimum_trade_notional: Decimal = Decimal("2.00")
    minimum_trade_fraction_of_nav: Decimal = Decimal("0.075")
    force_full_exits: bool = True

    def __post_init__(self) -> None:
        if (
            not self.minimum_trade_notional.is_finite()
            or self.minimum_trade_notional < _ZERO
        ):
            raise ValueError("minimum_trade_notional must be finite and non-negative")
        if (
            not self.minimum_trade_fraction_of_nav.is_finite()
            or self.minimum_trade_fraction_of_nav < _ZERO
            or self.minimum_trade_fraction_of_nav > _ONE
        ):
            raise ValueError("minimum_trade_fraction_of_nav must be in [0, 1]")


@dataclass(frozen=True)
class RebalanceInstruction:
    symbol: str
    current_weight: Decimal
    target_weight: Decimal
    delta_notional: Decimal
    execute: bool
    risk_reducing: bool
    reason: RebalanceReason


@dataclass(frozen=True)
class RebalancePlan:
    instructions: tuple[RebalanceInstruction, ...]
    threshold_notional: Decimal

    @property
    def executable_symbols(self) -> frozenset[str]:
        return frozenset(item.symbol for item in self.instructions if item.execute)

    @property
    def suppressed(self) -> tuple[RebalanceInstruction, ...]:
        return tuple(item for item in self.instructions if not item.execute)

    def for_symbol(self, symbol: str) -> RebalanceInstruction | None:
        for item in self.instructions:
            if item.symbol == symbol:
                return item
        return None


class EconomicRebalancePolicy:
    """Convert a desired target into deterministic trade/no-trade instructions.

    The policy is intentionally broker-independent. It uses only Project Fifty's internal
    point-in-time portfolio state, target weights and reference prices. Full exits may bypass the
    economic no-trade band because risk reduction must not be blocked merely to save friction.
    """

    def __init__(self, config: EconomicRebalanceConfig | None = None) -> None:
        self.config = config or EconomicRebalanceConfig()

    def plan(self, *, target: TargetPortfolio, context: StrategyContext) -> RebalancePlan:
        self._validate(target=target, context=context)
        nav = context.portfolio.nav
        threshold = max(
            self.config.minimum_trade_notional,
            nav * self.config.minimum_trade_fraction_of_nav,
        )

        instructions: list[RebalanceInstruction] = []
        symbols = sorted(set(context.portfolio.positions) | set(target.weights))
        for symbol in symbols:
            price = context.reference_prices.get(symbol)
            if price is None:
                raise ValueError(f"missing reference price for rebalance symbol {symbol}")

            position = context.portfolio.positions.get(symbol)
            current_quantity = position.quantity if position is not None else _ZERO
            current_notional = current_quantity * price
            current_weight = current_notional / nav if nav > _ZERO else _ZERO
            target_weight = target.weights.get(symbol, _ZERO)
            delta_notional = nav * target_weight - current_notional
            risk_reducing = delta_notional < _ZERO

            if delta_notional == _ZERO:
                instructions.append(
                    RebalanceInstruction(
                        symbol=symbol,
                        current_weight=current_weight,
                        target_weight=target_weight,
                        delta_notional=delta_notional,
                        execute=False,
                        risk_reducing=False,
                        reason=RebalanceReason.NO_CHANGE,
                    )
                )
                continue

            full_exit = current_quantity > _ZERO and target_weight == _ZERO
            if full_exit and self.config.force_full_exits:
                instructions.append(
                    RebalanceInstruction(
                        symbol=symbol,
                        current_weight=current_weight,
                        target_weight=target_weight,
                        delta_notional=delta_notional,
                        execute=True,
                        risk_reducing=True,
                        reason=RebalanceReason.FORCED_EXIT,
                    )
                )
                continue

            execute = abs(delta_notional) >= threshold
            instructions.append(
                RebalanceInstruction(
                    symbol=symbol,
                    current_weight=current_weight,
                    target_weight=target_weight,
                    delta_notional=delta_notional,
                    execute=execute,
                    risk_reducing=risk_reducing,
                    reason=(
                        RebalanceReason.EXECUTE
                        if execute
                        else RebalanceReason.BELOW_ECONOMIC_THRESHOLD
                    ),
                )
            )

        return RebalancePlan(instructions=tuple(instructions), threshold_notional=threshold)

    @staticmethod
    def _validate(*, target: TargetPortfolio, context: StrategyContext) -> None:
        if target.currency != context.currency:
            raise ValueError("target currency must match strategy context currency")
        if target.market_state_hash != context.market_state_hash:
            raise ValueError("target was not generated from the current market state")
        if target.as_of != context.as_of:
            raise ValueError("target timestamp must match strategy context timestamp")
        if not context.portfolio.nav.is_finite() or context.portfolio.nav < _ZERO:
            raise ValueError("portfolio NAV must be finite and non-negative")
