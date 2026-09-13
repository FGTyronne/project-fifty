from __future__ import annotations

from decimal import Decimal

from project_fifty.strategies.confirmed import (
    ConfirmedPersistentRegimeTechnicalStrategy,
)
from project_fifty.strategies.rebalance import (
    EconomicRebalanceConfig,
    EconomicRebalancePolicy,
)

M6_TIMEFRAME = "1Hour"
M6_STRATEGY_FACTORY = ConfirmedPersistentRegimeTechnicalStrategy


def m6_rebalance_policy() -> EconomicRebalancePolicy:
    """Return the frozen M6 economic policy shared by replay and future sessions."""
    return EconomicRebalancePolicy(
        EconomicRebalanceConfig(
            minimum_trade_notional=Decimal("3.00"),
            minimum_trade_fraction_of_nav=Decimal("0.10"),
            force_full_exits=True,
        )
    )
