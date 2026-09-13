from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Sequence

from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio

_ZERO = Decimal("0")
_ONE = Decimal("1")


class RegimeState(str, Enum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"
    SHOCK = "SHOCK"


@dataclass(frozen=True)
class BaselineConfig:
    """Configuration for the reproducible first strategy baseline.

    Risk budgets are desired strategy exposure only. They do not replace or expand the
    deterministic Project Fifty constitutional limits.
    """

    fast_ema_period: int = 12
    slow_ema_period: int = 26
    regime_fast_period: int = 20
    regime_slow_period: int = 50
    rsi_period: int = 14
    atr_period: int = 14
    breakout_period: int = 20
    short_momentum_lookback: int = 5
    medium_momentum_lookback: int = 20
    volume_lookback: int = 20
    max_positions: int = 2
    minimum_score: Decimal = Decimal("0.15")
    risk_on_budget: Decimal = Decimal("0.70")
    neutral_budget: Decimal = Decimal("0.40")
    risk_off_budget: Decimal = Decimal("0.15")

    def __post_init__(self) -> None:
        positive_periods = (
            self.fast_ema_period,
            self.slow_ema_period,
            self.regime_fast_period,
            self.regime_slow_period,
            self.rsi_period,
            self.atr_period,
            self.breakout_period,
            self.short_momentum_lookback,
            self.medium_momentum_lookback,
            self.volume_lookback,
            self.max_positions,
        )
        if any(value <= 0 for value in positive_periods):
            raise ValueError("strategy periods and max_positions must be positive")
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast EMA period must be shorter than slow EMA period")
        if self.regime_fast_period >= self.regime_slow_period:
            raise ValueError("regime fast period must be shorter than slow period")
        if self.minimum_score < -_ONE or self.minimum_score > _ONE:
            raise ValueError("minimum_score must be in [-1, 1]")
        for budget in (self.risk_on_budget, self.neutral_budget, self.risk_off_budget):
            if not budget.is_finite() or budget < _ZERO or budget > _ONE:
                raise ValueError("risk budgets must be finite and in [0, 1]")


@dataclass(frozen=True)
class SignalBreakdown:
    symbol: str
    score: Decimal
    trend: Decimal
    short_momentum: Decimal
    medium_momentum: Decimal
    mean_reversion: Decimal
    breakout: Decimal
    volume_confirmation: Decimal
    volatility_penalty: Decimal


class RegimeAwareTechnicalStrategy:
    """Deterministic long-only baseline inspired by mature public quant frameworks.

    The strategy deliberately combines a small set of distinct signal families instead of
    treating every named technical indicator as an independent vote. It emits portfolio
    weights only; it has no broker access and cannot approve its own orders.
    """

    strategy_id = "regime-aware-technical-baseline"
    strategy_version = "1.0.0"

    def __init__(self, config: BaselineConfig | None = None) -> None:
        self.config = config or BaselineConfig()

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        regime = self._detect_regime(context)
        budget = self._risk_budget(regime)
        evidence: dict[str, str] = {"regime": regime.value, "risk_budget": str(budget)}

        if budget == _ZERO:
            return self._cash_target(context, confidence=Decimal("0.90"), evidence=evidence)

        candidates: list[SignalBreakdown] = []
        for symbol in sorted(context.reference_prices):
            if symbol == context.benchmark_symbol:
                continue
            bars = context.history.get(symbol, ())
            signal = self._score_symbol(symbol, bars)
            if signal is None:
                evidence[f"{symbol}.status"] = "insufficient_history"
                continue
            evidence[f"{symbol}.score"] = str(signal.score)
            if signal.score >= self.config.minimum_score:
                candidates.append(signal)

        candidates.sort(key=lambda item: (-item.score, item.symbol))
        selected = candidates[: self.config.max_positions]
        if not selected:
            evidence["selection"] = "none_above_threshold"
            return self._cash_target(context, confidence=Decimal("0.50"), evidence=evidence)

        total_score = sum((item.score for item in selected), start=_ZERO)
        if total_score <= _ZERO:
            evidence["selection"] = "non_positive_composite"
            return self._cash_target(context, confidence=Decimal("0.50"), evidence=evidence)

        weights: dict[str, Decimal] = {}
        allocated = _ZERO
        for index, item in enumerate(selected):
            if index == len(selected) - 1:
                weight = budget - allocated
            else:
                weight = budget * item.score / total_score
                allocated += weight
            weights[item.symbol] = weight
            evidence[f"{item.symbol}.weight"] = str(weight)
            evidence[f"{item.symbol}.components"] = (
                f"trend={item.trend},short_mom={item.short_momentum},"
                f"medium_mom={item.medium_momentum},mean_reversion={item.mean_reversion},"
                f"breakout={item.breakout},volume={item.volume_confirmation},"
                f"vol_penalty={item.volatility_penalty}"
            )

        average_score = total_score / Decimal(len(selected))
        confidence = _clamp(average_score, _ZERO, _ONE)
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

    def _detect_regime(self, context: StrategyContext) -> RegimeState:
        benchmark = context.benchmark_symbol
        if benchmark is None:
            return RegimeState.NEUTRAL
        bars = context.history.get(benchmark, ())
        if len(bars) < self.config.regime_slow_period + 1:
            return RegimeState.NEUTRAL

        closes = [bar.close for bar in bars]
        current = closes[-1]
        previous = closes[-2]
        fast = _ema(closes, self.config.regime_fast_period)
        slow = _ema(closes, self.config.regime_slow_period)
        recent = closes[-self.config.regime_slow_period :]
        peak = max(recent)
        drawdown = current / peak - _ONE
        one_bar_return = current / previous - _ONE
        atr_ratio = _atr(bars, self.config.atr_period) / current

        if (
            one_bar_return <= Decimal("-0.04")
            or drawdown <= Decimal("-0.12")
            or atr_ratio >= Decimal("0.05")
        ):
            return RegimeState.SHOCK
        if drawdown <= Decimal("-0.08") or (
            current < slow and drawdown <= Decimal("-0.05")
        ):
            return RegimeState.RISK_OFF
        if (
            current > fast
            and fast > slow
            and drawdown > Decimal("-0.05")
            and atr_ratio < Decimal("0.035")
        ):
            return RegimeState.RISK_ON
        return RegimeState.NEUTRAL

    def _risk_budget(self, regime: RegimeState) -> Decimal:
        if regime == RegimeState.RISK_ON:
            return self.config.risk_on_budget
        if regime == RegimeState.RISK_OFF:
            return self.config.risk_off_budget
        if regime == RegimeState.SHOCK:
            return _ZERO
        return self.config.neutral_budget

    def _score_symbol(
        self,
        symbol: str,
        bars: Sequence[MarketBar],
    ) -> SignalBreakdown | None:
        required = max(
            self.config.slow_ema_period,
            self.config.medium_momentum_lookback + 1,
            self.config.rsi_period + 1,
            self.config.atr_period + 1,
            self.config.breakout_period,
            self.config.volume_lookback + 1,
        )
        if len(bars) < required:
            return None

        closes = [bar.close for bar in bars]
        fast = _ema(closes, self.config.fast_ema_period)
        slow = _ema(closes, self.config.slow_ema_period)
        trend = _clamp((fast / slow - _ONE) / Decimal("0.02"))
        short_momentum = _clamp(
            _roc(closes, self.config.short_momentum_lookback) / Decimal("0.03")
        )
        medium_momentum = _clamp(
            _roc(closes, self.config.medium_momentum_lookback) / Decimal("0.08")
        )

        rsi = _rsi(closes, self.config.rsi_period)
        mean_reversion = _clamp((Decimal("50") - rsi) / Decimal("30"))
        breakout = _clamp(
            (_range_position(bars, self.config.breakout_period) - Decimal("0.5")) * 2
        )
        volume_ratio = _volume_ratio(bars, self.config.volume_lookback)
        volume_direction = _sign(medium_momentum)
        volume_confirmation = _clamp((volume_ratio - _ONE) * volume_direction)
        atr_ratio = _atr(bars, self.config.atr_period) / closes[-1]
        volatility_penalty = _clamp(
            (atr_ratio - Decimal("0.015")) / Decimal("0.04"),
            _ZERO,
            _ONE,
        )

        score = (
            Decimal("0.28") * trend
            + Decimal("0.18") * short_momentum
            + Decimal("0.22") * medium_momentum
            + Decimal("0.10") * mean_reversion
            + Decimal("0.12") * breakout
            + Decimal("0.10") * volume_confirmation
            - Decimal("0.12") * volatility_penalty
        )
        score = _clamp(score)
        return SignalBreakdown(
            symbol=symbol,
            score=score,
            trend=trend,
            short_momentum=short_momentum,
            medium_momentum=medium_momentum,
            mean_reversion=mean_reversion,
            breakout=breakout,
            volume_confirmation=volume_confirmation,
            volatility_penalty=volatility_penalty,
        )

    def _cash_target(
        self,
        context: StrategyContext,
        *,
        confidence: Decimal,
        evidence: dict[str, str],
    ) -> TargetPortfolio:
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={},
            cash_weight=_ONE,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=confidence,
            market_state_hash=context.market_state_hash,
            evidence=evidence,
        )


def _ema(values: Sequence[Decimal], period: int) -> Decimal:
    if len(values) < period:
        raise ValueError("insufficient values for EMA")
    alpha = Decimal(2) / Decimal(period + 1)
    seed = sum(values[:period], start=_ZERO) / Decimal(period)
    value = seed
    for observation in values[period:]:
        value = observation * alpha + value * (_ONE - alpha)
    return value


def _roc(values: Sequence[Decimal], lookback: int) -> Decimal:
    if len(values) <= lookback:
        raise ValueError("insufficient values for ROC")
    previous = values[-lookback - 1]
    if previous <= 0:
        raise ValueError("ROC reference value must be positive")
    return values[-1] / previous - _ONE


def _rsi(values: Sequence[Decimal], period: int) -> Decimal:
    if len(values) <= period:
        raise ValueError("insufficient values for RSI")
    changes = [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]
    gains = sum((max(change, _ZERO) for change in changes), start=_ZERO) / Decimal(period)
    losses = sum((max(-change, _ZERO) for change in changes), start=_ZERO) / Decimal(period)
    if losses == _ZERO:
        return Decimal("100") if gains > _ZERO else Decimal("50")
    if gains == _ZERO:
        return _ZERO
    relative_strength = gains / losses
    return Decimal("100") - Decimal("100") / (_ONE + relative_strength)


def _atr(bars: Sequence[MarketBar], period: int) -> Decimal:
    if len(bars) <= period:
        raise ValueError("insufficient bars for ATR")
    true_ranges: list[Decimal] = []
    start = len(bars) - period
    for index in range(start, len(bars)):
        bar = bars[index]
        previous_close = bars[index - 1].close
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
    return sum(true_ranges, start=_ZERO) / Decimal(period)


def _range_position(bars: Sequence[MarketBar], lookback: int) -> Decimal:
    if len(bars) < lookback:
        raise ValueError("insufficient bars for range position")
    recent = bars[-lookback:]
    high = max(bar.high for bar in recent)
    low = min(bar.low for bar in recent)
    if high == low:
        return Decimal("0.5")
    return (recent[-1].close - low) / (high - low)


def _volume_ratio(bars: Sequence[MarketBar], lookback: int) -> Decimal:
    if len(bars) <= lookback:
        raise ValueError("insufficient bars for volume ratio")
    prior = bars[-lookback - 1 : -1]
    average = sum((bar.volume for bar in prior), start=_ZERO) / Decimal(lookback)
    if average == _ZERO:
        return _ONE
    return bars[-1].volume / average


def _sign(value: Decimal) -> Decimal:
    if value > _ZERO:
        return _ONE
    if value < _ZERO:
        return Decimal("-1")
    return _ZERO


def _clamp(
    value: Decimal,
    lower: Decimal = Decimal("-1"),
    upper: Decimal = _ONE,
) -> Decimal:
    return min(max(value, lower), upper)
