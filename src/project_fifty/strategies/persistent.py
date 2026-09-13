from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from project_fifty.strategies.baseline import (
    BaselineConfig,
    RegimeAwareTechnicalStrategy,
    SignalBreakdown,
)
from project_fifty.strategies.contracts import StrategyContext, TargetPortfolio

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True)
class PersistentBaselineConfig:
    """Predeclared M5 persistence controls for baseline v2."""

    signal_config: BaselineConfig = field(default_factory=BaselineConfig)
    entry_score: Decimal = Decimal("0.25")
    retention_score: Decimal = Decimal("0.05")
    replacement_margin: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        for name, value in (
            ("entry_score", self.entry_score),
            ("retention_score", self.retention_score),
            ("replacement_margin", self.replacement_margin),
        ):
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
        if self.entry_score < Decimal("-1") or self.entry_score > _ONE:
            raise ValueError("entry_score must be in [-1, 1]")
        if self.retention_score < Decimal("-1") or self.retention_score > _ONE:
            raise ValueError("retention_score must be in [-1, 1]")
        if self.retention_score > self.entry_score:
            raise ValueError("retention_score must not exceed entry_score")
        if self.replacement_margin < _ZERO or self.replacement_margin > Decimal("2"):
            raise ValueError("replacement_margin must be in [0, 2]")


class PersistentRegimeTechnicalStrategy(RegimeAwareTechnicalStrategy):
    """M5 baseline v2 with incumbent hysteresis and stable equal weights.

    The signal families and regime detector remain the published v1 baseline. The economic change
    is deliberately narrow: acceptable incumbents persist, challengers need a material score edge
    to displace a full portfolio, and selected positions receive equal weights so harmless score
    noise does not continuously alter target notionals.
    """

    strategy_id = "regime-aware-technical-baseline"
    strategy_version = "2.0.0"

    def __init__(self, config: PersistentBaselineConfig | None = None) -> None:
        self.persistent_config = config or PersistentBaselineConfig()
        super().__init__(self.persistent_config.signal_config)

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        regime = self._detect_regime(context)
        budget = self._risk_budget(regime)
        evidence: dict[str, str] = {
            "regime": regime.value,
            "risk_budget": str(budget),
            "entry_score": str(self.persistent_config.entry_score),
            "retention_score": str(self.persistent_config.retention_score),
            "replacement_margin": str(self.persistent_config.replacement_margin),
        }

        if budget == _ZERO:
            evidence["selection"] = "risk_budget_zero"
            return self._cash_target(context, confidence=Decimal("0.90"), evidence=evidence)

        signals: dict[str, SignalBreakdown] = {}
        for symbol in sorted(context.reference_prices):
            if symbol == context.benchmark_symbol:
                continue
            signal = self._score_symbol(symbol, context.history.get(symbol, ()))
            if signal is None:
                evidence[f"{symbol}.status"] = "insufficient_history"
                continue
            signals[symbol] = signal
            evidence[f"{symbol}.score"] = str(signal.score)

        incumbent_symbols = {
            symbol
            for symbol in context.portfolio.positions
            if symbol != context.benchmark_symbol
        }
        retained = sorted(
            (
                signal
                for symbol, signal in signals.items()
                if symbol in incumbent_symbols
                and signal.score >= self.persistent_config.retention_score
            ),
            key=lambda item: (-item.score, item.symbol),
        )[: self.config.max_positions]

        selected: list[SignalBreakdown] = list(retained)
        challengers = sorted(
            (
                signal
                for symbol, signal in signals.items()
                if symbol not in {item.symbol for item in selected}
                and signal.score >= self.persistent_config.entry_score
            ),
            key=lambda item: (-item.score, item.symbol),
        )

        while challengers and len(selected) < self.config.max_positions:
            candidate = challengers.pop(0)
            selected.append(candidate)
            evidence[f"{candidate.symbol}.selection"] = "filled_open_slot"

        for candidate in challengers:
            if not selected:
                break
            weakest = min(selected, key=lambda item: (item.score, item.symbol))
            required = weakest.score + self.persistent_config.replacement_margin
            if candidate.score < required:
                evidence[f"{candidate.symbol}.selection"] = (
                    f"challenger_rejected_required_score={required}"
                )
                continue
            selected.remove(weakest)
            selected.append(candidate)
            evidence[f"{weakest.symbol}.selection"] = (
                f"replaced_by={candidate.symbol}"
            )
            evidence[f"{candidate.symbol}.selection"] = (
                f"replaced={weakest.symbol}"
            )

        selected.sort(key=lambda item: (-item.score, item.symbol))
        if not selected:
            evidence["selection"] = "no_persistent_candidate"
            return self._cash_target(context, confidence=Decimal("0.50"), evidence=evidence)

        weight = budget / Decimal(len(selected))
        weights = {item.symbol: weight for item in selected}
        for item in selected:
            evidence[f"{item.symbol}.weight"] = str(weight)
            if item.symbol in incumbent_symbols and f"{item.symbol}.selection" not in evidence:
                evidence[f"{item.symbol}.selection"] = "incumbent_retained"
            evidence[f"{item.symbol}.components"] = (
                f"trend={item.trend},short_mom={item.short_momentum},"
                f"medium_mom={item.medium_momentum},mean_reversion={item.mean_reversion},"
                f"breakout={item.breakout},volume={item.volume_confirmation},"
                f"vol_penalty={item.volatility_penalty}"
            )

        average_score = sum((item.score for item in selected), start=_ZERO) / Decimal(
            len(selected)
        )
        confidence = min(max(average_score, _ZERO), _ONE)
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights=weights,
            cash_weight=_ONE - budget,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=confidence,
            market_state_hash=context.market_state_hash,
            evidence=evidence,
        )
