from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from project_fifty.strategies.baseline import (
    RegimeState,
    _atr,
    _ema,
)
from project_fifty.strategies.confirmed import ConfirmedPersistentRegimeTechnicalStrategy
from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio

_ONE = Decimal("1")


@dataclass(frozen=True)
class RegimePersistenceDiagnostics:
    raw_regime: RegimeState
    effective_regime: RegimeState
    recent_raw_regimes: tuple[RegimeState, ...]
    reason: str


class RegimePersistentConfirmedStrategy(ConfirmedPersistentRegimeTechnicalStrategy):
    """M7 baseline v4 with asymmetric restart-safe regime persistence.

    Adverse states de-risk immediately. Increasing exposure requires confirmation from completed
    benchmark bars. The implementation contains no process-local regime counter, so replaying the
    same point-in-time history after restart produces the same effective regime.
    """

    strategy_id = "regime-aware-technical-baseline"
    strategy_version = "4.0.0"
    regime_confirmation_bars = 3

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        diagnostics = self.regime_diagnostics(context)
        target = super().generate_target(context)
        evidence = dict(target.evidence)
        evidence.update(
            {
                "raw_regime": diagnostics.raw_regime.value,
                "effective_regime": diagnostics.effective_regime.value,
                "recent_raw_regimes": ",".join(
                    regime.value for regime in diagnostics.recent_raw_regimes
                ),
                "regime_transition_reason": diagnostics.reason,
            }
        )
        return target.model_copy(update={"evidence": evidence})

    def _detect_regime(self, context: StrategyContext) -> RegimeState:
        return self.regime_diagnostics(context).effective_regime

    def regime_diagnostics(self, context: StrategyContext) -> RegimePersistenceDiagnostics:
        benchmark = context.benchmark_symbol
        if benchmark is None:
            return RegimePersistenceDiagnostics(
                raw_regime=RegimeState.NEUTRAL,
                effective_regime=RegimeState.NEUTRAL,
                recent_raw_regimes=(),
                reason="NO_BENCHMARK",
            )
        bars = context.history.get(benchmark, ())
        sequence = self._recent_raw_regimes(bars, self.regime_confirmation_bars)
        raw = sequence[-1] if sequence else RegimeState.NEUTRAL

        if raw == RegimeState.SHOCK:
            return RegimePersistenceDiagnostics(raw, RegimeState.SHOCK, sequence, "SHOCK_EXIT")
        if raw == RegimeState.RISK_OFF:
            return RegimePersistenceDiagnostics(
                raw,
                RegimeState.RISK_OFF,
                sequence,
                "RISK_OFF_IMMEDIATE",
            )
        if len(sequence) < self.regime_confirmation_bars:
            return RegimePersistenceDiagnostics(
                raw,
                RegimeState.NEUTRAL,
                sequence,
                "INSUFFICIENT_REGIME_CONFIRMATION",
            )
        if all(regime == RegimeState.RISK_ON for regime in sequence):
            return RegimePersistenceDiagnostics(
                raw,
                RegimeState.RISK_ON,
                sequence,
                "RISK_ON_CONFIRMED",
            )
        if any(regime in {RegimeState.RISK_OFF, RegimeState.SHOCK} for regime in sequence):
            return RegimePersistenceDiagnostics(
                raw,
                RegimeState.RISK_OFF,
                sequence,
                "RECOVERY_UNCONFIRMED",
            )
        if raw == RegimeState.RISK_ON:
            return RegimePersistenceDiagnostics(
                raw,
                RegimeState.NEUTRAL,
                sequence,
                "RISK_ON_UNCONFIRMED",
            )
        return RegimePersistenceDiagnostics(
            raw,
            RegimeState.NEUTRAL,
            sequence,
            "NEUTRAL_CONFIRMED",
        )

    def _recent_raw_regimes(
        self,
        bars: tuple[MarketBar, ...],
        count: int,
    ) -> tuple[RegimeState, ...]:
        if not bars:
            return ()
        first_end = max(1, len(bars) - count + 1)
        return tuple(
            self._raw_regime_for_bars(bars[:end_index])
            for end_index in range(first_end, len(bars) + 1)
        )

    def _raw_regime_for_bars(self, bars: tuple[MarketBar, ...]) -> RegimeState:
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
