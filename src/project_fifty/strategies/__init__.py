"""Strategy contracts and portfolio-target composition for Project Fifty."""

from project_fifty.strategies.baseline import (
    BaselineConfig,
    RegimeAwareTechnicalStrategy,
    RegimeState,
)
from project_fifty.strategies.confirmed import (
    ConfirmedPersistentConfig,
    ConfirmedPersistentRegimeTechnicalStrategy,
)
from project_fifty.strategies.contracts import MarketBar, StrategyProvider, TargetPortfolio
from project_fifty.strategies.low_frequency import (
    LowFrequencyMomentumConfig,
    LowFrequencyMomentumStrategy,
)
from project_fifty.strategies.persistent import (
    PersistentBaselineConfig,
    PersistentRegimeTechnicalStrategy,
)
from project_fifty.strategies.proposal_builder import ProposalBuilder
from project_fifty.strategies.rebalance import (
    EconomicRebalanceConfig,
    EconomicRebalancePolicy,
    RebalanceInstruction,
    RebalancePlan,
    RebalanceReason,
)
from project_fifty.strategies.regime_persistent import (
    RegimePersistenceDiagnostics,
    RegimePersistentConfirmedStrategy,
)
from project_fifty.strategies.single_market import (
    SingleMarketTrendConfig,
    SingleMarketTrendStrategy,
)

__all__ = [
    "BaselineConfig",
    "ConfirmedPersistentConfig",
    "ConfirmedPersistentRegimeTechnicalStrategy",
    "EconomicRebalanceConfig",
    "EconomicRebalancePolicy",
    "LowFrequencyMomentumConfig",
    "LowFrequencyMomentumStrategy",
    "MarketBar",
    "PersistentBaselineConfig",
    "PersistentRegimeTechnicalStrategy",
    "ProposalBuilder",
    "RebalanceInstruction",
    "RebalancePlan",
    "RebalanceReason",
    "RegimeAwareTechnicalStrategy",
    "RegimePersistenceDiagnostics",
    "RegimePersistentConfirmedStrategy",
    "RegimeState",
    "SingleMarketTrendConfig",
    "SingleMarketTrendStrategy",
    "StrategyProvider",
    "TargetPortfolio",
]
