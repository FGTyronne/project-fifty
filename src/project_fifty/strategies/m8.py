from __future__ import annotations

from decimal import Decimal

from project_fifty.strategies.low_frequency import LowFrequencyMomentumStrategy
from project_fifty.strategies.rebalance import EconomicRebalanceConfig, EconomicRebalancePolicy

M8_TIMEFRAME = "1Day"
M8_STRATEGY_FACTORY = LowFrequencyMomentumStrategy


def m8_rebalance_policy() -> EconomicRebalancePolicy:
    """Frozen M8 economic filter shared by replay and future autonomous sessions."""
    return EconomicRebalancePolicy(
        EconomicRebalanceConfig(
            minimum_trade_notional=Decimal("5.00"),
            minimum_trade_fraction_of_nav=Decimal("0.15"),
            force_full_exits=True,
        )
    )
