from __future__ import annotations

from project_fifty.strategies.m8 import m8_rebalance_policy
from project_fifty.strategies.rebalance import EconomicRebalancePolicy
from project_fifty.strategies.single_market import SingleMarketTrendStrategy

M9_TIMEFRAME = "1Day"
M9_STRATEGY_FACTORY = SingleMarketTrendStrategy


def m9_rebalance_policy() -> EconomicRebalancePolicy:
    """M9 deliberately retains the frozen M8 economic filter unchanged."""
    return m8_rebalance_policy()
