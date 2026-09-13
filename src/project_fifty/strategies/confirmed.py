from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from project_fifty.strategies.baseline import (
    BaselineConfig,
    RegimeAwareTechnicalStrategy,
    RegimeState,
    SignalBreakdown,
)
from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True)
class ConfirmedPersistentConfig:
    """Predeclared M6 confirmation controls for baseline v3."""

    signal_config: BaselineConfig = field(default_factory=BaselineConfig)
    entry_score: Decimal = Decimal("0.25")
    retention_score: Decimal = Decimal("0.05")
    replacement_margin: Decimal = Decimal("0.10")
    entry_confirmation_bars: int = 2
    exit_confirmation_bars: int = 3
    replacement_confirmation_bars: int = 3

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
        if min(
            self.entry_confirmation_bars,
            self.exit_confirmation_bars,
            self.replacement_confirmation_bars,
        ) <= 0:
            raise ValueError("confirmation bars must be positive")


class ConfirmedPersistentRegimeTechnicalStrategy(RegimeAwareTechnicalStrategy):
    """M6 baseline v3 with restart-safe historical confirmation.

    Ordinary entries, exits and replacements are confirmed from the most recent completed bars.
    The strategy keeps no process-local counters, so a restart cannot erase or manufacture a
    confirmation streak. Zero risk budget remains an immediate move-to-cash condition.
    """

    strategy_id = "regime-aware-technical-baseline"
    strategy_version = "3.0.0"

    def __init__(self, config: ConfirmedPersistentConfig | None = None) -> None:
        self.confirmed_config = config or ConfirmedPersistentConfig()
        super().__init__(self.confirmed_config.signal_config)

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        regime = self._detect_regime(context)
        budget = self._risk_budget(regime)
        cfg = self.confirmed_config
        evidence: dict[str, str] = {
            "regime": regime.value,
            "risk_budget": str(budget),
            "entry_score": str(cfg.entry_score),
            "retention_score": str(cfg.retention_score),
            "replacement_margin": str(cfg.replacement_margin),
            "entry_confirmation_bars": str(cfg.entry_confirmation_bars),
            "exit_confirmation_bars": str(cfg.exit_confirmation_bars),
            "replacement_confirmation_bars": str(cfg.replacement_confirmation_bars),
        }

        if budget == _ZERO:
            evidence["selection"] = "SHOCK_EXIT" if regime == RegimeState.SHOCK else "ZERO_BUDGET_EXIT"
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

        selected: list[SignalBreakdown] = []
        for symbol in sorted(incumbent_symbols):
            signal = signals.get(symbol)
            if signal is None:
                evidence[f"{symbol}.selection"] = "EXIT_UNCONFIRMED"
                continue
            if signal.score >= cfg.retention_score:
                selected.append(signal)
                evidence[f"{symbol}.selection"] = "INCUMBENT_RETAINED"
                continue
            if self._threshold_confirmed(
                symbol=symbol,
                bars=context.history.get(symbol, ()),
                count=cfg.exit_confirmation_bars,
                threshold=cfg.retention_score,
                comparison="below",
            ):
                evidence[f"{symbol}.selection"] = "EXIT_CONFIRMED"
                continue
            selected.append(signal)
            evidence[f"{symbol}.selection"] = "EXIT_UNCONFIRMED"

        selected.sort(key=lambda item: (-item.score, item.symbol))
        if len(selected) > self.config.max_positions:
            selected = selected[: self.config.max_positions]

        selected_symbols = {item.symbol for item in selected}
        challengers: list[SignalBreakdown] = []
        for symbol, signal in signals.items():
            if symbol in incumbent_symbols or symbol in selected_symbols:
                continue
            if signal.score < cfg.entry_score:
                continue
            if not self._threshold_confirmed(
                symbol=symbol,
                bars=context.history.get(symbol, ()),
                count=cfg.entry_confirmation_bars,
                threshold=cfg.entry_score,
                comparison="at_least",
            ):
                evidence[f"{symbol}.selection"] = "ENTRY_UNCONFIRMED"
                continue
            challengers.append(signal)

        challengers.sort(key=lambda item: (-item.score, item.symbol))
        while challengers and len(selected) < self.config.max_positions:
            candidate = challengers.pop(0)
            selected.append(candidate)
            evidence[f"{candidate.symbol}.selection"] = "ENTRY_CONFIRMED"

        for candidate in challengers:
            if not selected:
                break
            weakest = min(selected, key=lambda item: (item.score, item.symbol))
            if not self._replacement_confirmed(
                challenger=candidate.symbol,
                incumbent=weakest.symbol,
                challenger_bars=context.history.get(candidate.symbol, ()),
                incumbent_bars=context.history.get(weakest.symbol, ()),
                count=cfg.replacement_confirmation_bars,
                margin=cfg.replacement_margin,
            ):
                evidence[f"{candidate.symbol}.selection"] = "REPLACEMENT_UNCONFIRMED"
                continue
            selected.remove(weakest)
            selected.append(candidate)
            evidence[f"{weakest.symbol}.selection"] = f"REPLACED_BY={candidate.symbol}"
            evidence[f"{candidate.symbol}.selection"] = f"REPLACEMENT_CONFIRMED={weakest.symbol}"

        selected.sort(key=lambda item: (-item.score, item.symbol))
        if not selected:
            evidence["selection"] = "NO_CONFIRMED_POSITION"
            return self._cash_target(context, confidence=Decimal("0.50"), evidence=evidence)

        weight = budget / Decimal(len(selected))
        weights = {item.symbol: weight for item in selected}
        for item in selected:
            evidence[f"{item.symbol}.weight"] = str(weight)
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

    def _threshold_confirmed(
        self,
        *,
        symbol: str,
        bars: tuple[MarketBar, ...],
        count: int,
        threshold: Decimal,
        comparison: str,
    ) -> bool:
        series = self._recent_score_series(symbol=symbol, bars=bars, count=count)
        if series is None:
            return False
        scores = [score for _, score in series]
        if comparison == "below":
            return all(score < threshold for score in scores)
        if comparison == "at_least":
            return all(score >= threshold for score in scores)
        raise ValueError("unsupported confirmation comparison")

    def _replacement_confirmed(
        self,
        *,
        challenger: str,
        incumbent: str,
        challenger_bars: tuple[MarketBar, ...],
        incumbent_bars: tuple[MarketBar, ...],
        count: int,
        margin: Decimal,
    ) -> bool:
        challenger_series = self._recent_score_series(
            symbol=challenger,
            bars=challenger_bars,
            count=count,
        )
        incumbent_series = self._recent_score_series(
            symbol=incumbent,
            bars=incumbent_bars,
            count=count,
        )
        if challenger_series is None or incumbent_series is None:
            return False
        if [timestamp for timestamp, _ in challenger_series] != [
            timestamp for timestamp, _ in incumbent_series
        ]:
            return False
        return all(
            challenger_score >= incumbent_score + margin
            for (_, challenger_score), (_, incumbent_score) in zip(
                challenger_series,
                incumbent_series,
                strict=True,
            )
        )

    def _recent_score_series(
        self,
        *,
        symbol: str,
        bars: tuple[MarketBar, ...],
        count: int,
    ) -> tuple[tuple[object, Decimal], ...] | None:
        if len(bars) < count:
            return None
        start_end = len(bars) - count + 1
        series: list[tuple[object, Decimal]] = []
        for end_index in range(start_end, len(bars) + 1):
            window = bars[:end_index]
            signal = self._score_symbol(symbol, window)
            if signal is None:
                return None
            series.append((window[-1].timestamp, signal.score))
        return tuple(series)
