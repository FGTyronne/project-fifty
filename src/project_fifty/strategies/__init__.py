"""Strategy contracts and portfolio-target composition for Project Fifty."""

from project_fifty.strategies.baseline import (
    BaselineConfig,
    RegimeAwareTechnicalStrategy,
    RegimeState,
)
from project_fifty.strategies.contracts import MarketBar, StrategyProvider, TargetPortfolio
from project_fifty.strategies.proposal_builder import ProposalBuilder

__all__ = [
    "BaselineConfig",
    "MarketBar",
    "ProposalBuilder",
    "RegimeAwareTechnicalStrategy",
    "RegimeState",
    "StrategyProvider",
    "TargetPortfolio",
]
