from __future__ import annotations

from project_fifty.ledger.base import Ledger
from project_fifty.strategies.contracts import StrategyContext, StrategyProvider, TargetPortfolio


class AuditedStrategy:
    """Record every deterministic target, including valid no-trade decisions."""

    def __init__(self, *, delegate: StrategyProvider, ledger: Ledger) -> None:
        self._delegate = delegate
        self._ledger = ledger

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        target = self._delegate.generate_target(context)
        self._ledger.append(
            "strategy_target_generated",
            {
                "as_of": target.as_of.isoformat(),
                "strategy_id": target.strategy_id,
                "strategy_version": target.strategy_version,
                "market_state_hash": target.market_state_hash,
                "weights": {symbol: str(weight) for symbol, weight in target.weights.items()},
                "cash_weight": str(target.cash_weight),
                "confidence": str(target.confidence),
                "evidence": dict(target.evidence),
            },
        )
        return target
