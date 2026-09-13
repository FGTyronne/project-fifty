from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True)
class LowFrequencyMomentumConfig:
    """Frozen M8 parameters for the low-frequency daily baseline."""

    rebalance_every_bars: int = 5
    benchmark_sma_days: int = 100
    candidate_sma_days: int = 50
    momentum_days: int = 63
    target_risk_weight: Decimal = Decimal("0.70")
    replacement_margin: Decimal = Decimal("0.05")

    def __post_init__(self) -> None:
        if min(
            self.rebalance_every_bars,
            self.benchmark_sma_days,
            self.candidate_sma_days,
            self.momentum_days,
        ) <= 0:
            raise ValueError("M8 lookbacks and cadence must be positive")
        if not self.target_risk_weight.is_finite() or not (
            _ZERO < self.target_risk_weight < _ONE
        ):
            raise ValueError("target_risk_weight must be finite and in (0, 1)")
        if not self.replacement_margin.is_finite() or not (
            _ZERO <= self.replacement_margin <= _ONE
        ):
            raise ValueError("replacement_margin must be finite and in [0, 1]")


class LowFrequencyMomentumStrategy:
    """M8 v5 daily baseline with structural turnover suppression.

    Ordinary allocation changes occur only every five completed benchmark bars. Between scheduled
    decisions the strategy returns the marked current portfolio weights, so price drift does not
    create mechanical rebalancing. All state is derived from StrategyContext and completed bars.
    """

    strategy_id = "low-frequency-momentum-baseline"
    strategy_version = "5.0.0"

    def __init__(self, config: LowFrequencyMomentumConfig | None = None) -> None:
        self.config = config or LowFrequencyMomentumConfig()

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        benchmark_symbol = context.benchmark_symbol
        if benchmark_symbol is None:
            return self._preserve(context, reason="NO_BENCHMARK")

        benchmark = context.history.get(benchmark_symbol, ())
        minimum_history = max(
            self.config.benchmark_sma_days,
            self.config.momentum_days + 1,
        )
        if len(benchmark) < minimum_history:
            return self._preserve(context, reason="INSUFFICIENT_BENCHMARK_HISTORY")

        if len(benchmark) % self.config.rebalance_every_bars != 0:
            return self._preserve(context, reason="NOT_SCHEDULED")

        benchmark_momentum = self._momentum(benchmark)
        benchmark_sma = self._sma(benchmark, self.config.benchmark_sma_days)
        benchmark_close = benchmark[-1].close
        evidence: dict[str, str] = {
            "scheduled": "true",
            "benchmark": benchmark_symbol,
            "benchmark_close": str(benchmark_close),
            "benchmark_sma": str(benchmark_sma),
            "benchmark_momentum_63d": str(benchmark_momentum),
            "rebalance_every_bars": str(self.config.rebalance_every_bars),
            "target_risk_weight": str(self.config.target_risk_weight),
            "replacement_margin": str(self.config.replacement_margin),
        }

        if benchmark_close <= benchmark_sma or benchmark_momentum <= _ZERO:
            evidence["selection"] = "BENCHMARK_RISK_GATE_OFF"
            return self._cash(context, evidence=evidence)

        eligible: dict[str, Decimal] = {}
        required_candidate_history = max(
            self.config.candidate_sma_days,
            self.config.momentum_days + 1,
        )
        for symbol in sorted(context.reference_prices):
            if symbol == benchmark_symbol:
                continue
            bars = context.history.get(symbol, ())
            if len(bars) < required_candidate_history:
                evidence[f"{symbol}.status"] = "INSUFFICIENT_HISTORY"
                continue
            momentum = self._momentum(bars)
            sma = self._sma(bars, self.config.candidate_sma_days)
            close = bars[-1].close
            evidence[f"{symbol}.momentum_63d"] = str(momentum)
            evidence[f"{symbol}.sma_50d"] = str(sma)
            if close > sma and momentum > _ZERO:
                eligible[symbol] = momentum
                evidence[f"{symbol}.status"] = "ELIGIBLE"
            else:
                evidence[f"{symbol}.status"] = "INELIGIBLE"

        if not eligible:
            evidence["selection"] = "NO_ELIGIBLE_CANDIDATE"
            return self._cash(context, evidence=evidence)

        ranked = sorted(eligible.items(), key=lambda item: (-item[1], item[0]))
        challenger, challenger_momentum = ranked[0]
        incumbents = sorted(
            symbol
            for symbol in context.portfolio.positions
            if symbol != benchmark_symbol
        )

        if not incumbents:
            evidence["selection"] = f"ENTRY={challenger}"
            return self._single_position(context, symbol=challenger, evidence=evidence)

        incumbent = incumbents[0]
        incumbent_momentum = eligible.get(incumbent)
        if incumbent_momentum is None:
            evidence["selection"] = f"REPLACE_INELIGIBLE={incumbent}->{challenger}"
            return self._single_position(context, symbol=challenger, evidence=evidence)

        if challenger == incumbent:
            evidence["selection"] = f"HOLD_INCUMBENT={incumbent}"
            return self._preserve(context, reason="INCUMBENT_BEST", evidence=evidence)

        if challenger_momentum >= incumbent_momentum + self.config.replacement_margin:
            evidence["selection"] = f"REPLACE={incumbent}->{challenger}"
            evidence["replacement_edge"] = str(challenger_momentum - incumbent_momentum)
            return self._single_position(context, symbol=challenger, evidence=evidence)

        evidence["selection"] = f"HOLD_INCUMBENT={incumbent}"
        evidence["challenger"] = challenger
        evidence["replacement_edge"] = str(challenger_momentum - incumbent_momentum)
        return self._preserve(context, reason="REPLACEMENT_MARGIN_NOT_MET", evidence=evidence)

    def _momentum(self, bars: tuple[MarketBar, ...]) -> Decimal:
        current = bars[-1].close
        previous = bars[-(self.config.momentum_days + 1)].close
        return current / previous - _ONE

    @staticmethod
    def _sma(bars: tuple[MarketBar, ...], days: int) -> Decimal:
        closes = [bar.close for bar in bars[-days:]]
        return sum(closes, start=_ZERO) / Decimal(days)

    def _single_position(
        self,
        context: StrategyContext,
        *,
        symbol: str,
        evidence: dict[str, str],
    ) -> TargetPortfolio:
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={symbol: self.config.target_risk_weight},
            cash_weight=_ONE - self.config.target_risk_weight,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("0.50"),
            market_state_hash=context.market_state_hash,
            evidence=evidence,
        )

    def _cash(
        self,
        context: StrategyContext,
        *,
        evidence: dict[str, str],
    ) -> TargetPortfolio:
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={},
            cash_weight=_ONE,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("0.50"),
            market_state_hash=context.market_state_hash,
            evidence=evidence,
        )

    def _preserve(
        self,
        context: StrategyContext,
        *,
        reason: str,
        evidence: dict[str, str] | None = None,
    ) -> TargetPortfolio:
        preserved_evidence = dict(evidence or {})
        preserved_evidence.setdefault("scheduled", "false")
        preserved_evidence.setdefault("selection", reason)

        if context.portfolio.nav <= _ZERO or not context.portfolio.positions:
            return self._cash(context, evidence=preserved_evidence)

        weights: dict[str, Decimal] = {}
        for symbol, position in sorted(context.portfolio.positions.items()):
            price = context.reference_prices.get(symbol)
            if price is None:
                raise ValueError(f"missing reference price for current position {symbol}")
            weight = position.quantity * price / context.portfolio.nav
            if weight < _ZERO or weight > _ONE:
                raise ValueError("current position weight escaped [0, 1]")
            weights[symbol] = weight

        invested = sum(weights.values(), start=_ZERO)
        if invested > _ONE:
            raise ValueError("current invested weight exceeds 100%")
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights=weights,
            cash_weight=_ONE - invested,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("0.50"),
            market_state_hash=context.market_state_hash,
            evidence=preserved_evidence,
        )
