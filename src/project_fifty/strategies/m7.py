from __future__ import annotations

from project_fifty.strategies.m6 import m6_rebalance_policy
from project_fifty.strategies.rebalance import EconomicRebalancePolicy
from project_fifty.strategies.regime_persistent import RegimePersistentConfirmedStrategy

M7_TIMEFRAME = "1Hour"
M7_STRATEGY_FACTORY = RegimePersistentConfirmedStrategy


def m7_rebalance_policy() -> EconomicRebalancePolicy:
    """M7 deliberately keeps the frozen M6 economic filter unchanged."""
    return m6_rebalance_policy()
