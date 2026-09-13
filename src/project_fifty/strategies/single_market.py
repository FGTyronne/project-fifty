from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True)
class SingleMarketTrendConfig:
    """Frozen M9 parameters for the SPY-only trend/cash baseline."""

    symbol: str = "SPY"
    rebalance_every_bars: int = 21
    trend_sma_days: int = 200
    momentum_days: int = 126

    def __post_init__(self) -> None:
        if self.symbol.strip().upper() != "SPY":
            raise ValueError("M9 is frozen to SPY only")
        if min(
            self.rebalance_every_bars,
            self.trend_sma_days,
            self.momentum_days,
        ) <= 0:
            raise ValueError("M9 cadence and lookbacks must be positive")


class SingleMarketTrendStrategy:
    """M9 v6 SPY/cash strategy with transition-only trading.

    Decisions are based solely on completed SPY daily bars. The strategy checks its risk state only
    every 21 completed bars. If the state is unchanged, it preserves the marked portfolio rather
    than mechanically rebalancing. This creates structurally low turnover and requires no
    process-local state.
    """

    strategy_id = "single-market-trend-baseline"
    strategy_version = "6.0.0"

    def __init__(self, config: SingleMarketTrendConfig | None = None) -> None:
        self.config = config or SingleMarketTrendConfig()

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        symbol = self.config.symbol
        if context.benchmark_symbol != symbol:
            raise ValueError("M9 requires SPY as the benchmark and sole risk instrument")
        unexpected = set(context.portfolio.positions) - {symbol}
        if unexpected:
            raise ValueError("M9 encountered a non-SPY position")

        bars = context.history.get(symbol, ())
        minimum_history = max(self.config.trend_sma_days, self.config.momentum_days + 1)
        if len(bars) < minimum_history:
            return self._preserve(context, reason="INSUFFICIENT_HISTORY")

        if len(bars) % self.config.rebalance_every_bars != 0:
            return self._preserve(context, reason="NOT_SCHEDULED")

        close = bars[-1].close
        sma = self._sma(bars, self.config.trend_sma_days)
        momentum = self._momentum(bars)
        risk_on = close > sma and momentum > _ZERO
        evidence = {
            "scheduled": "true",
            "symbol": symbol,
            "close": str(close),
            "sma_200d": str(sma),
            "momentum_126d": str(momentum),
            "raw_risk_state": "RISK_ON" if risk_on else "RISK_OFF",
            "rebalance_every_bars": str(self.config.rebalance_every_bars),
        }

        if risk_on:
            if symbol in context.portfolio.positions:
                evidence["selection"] = "HOLD_RISK_ON"
                return self._preserve(context, reason="HOLD_RISK_ON", evidence=evidence)
            evidence["selection"] = "ENTER_RISK_ON"
            return TargetPortfolio(
                as_of=context.as_of,
                currency=context.currency,
                weights={symbol: _ONE},
                cash_weight=_ZERO,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                confidence=Decimal("0.50"),
                market_state_hash=context.market_state_hash,
                evidence=evidence,
            )

        evidence["selection"] = "EXIT_TO_CASH" if symbol in context.portfolio.positions else "HOLD_CASH"
        return self._cash(context, evidence=evidence)

    def _momentum(self, bars: tuple[MarketBar, ...]) -> Decimal:
        current = bars[-1].close
        previous = bars[-(self.config.momentum_days + 1)].close
        return current / previous - _ONE

    @staticmethod
    def _sma(bars: tuple[MarketBar, ...], days: int) -> Decimal:
        closes = [bar.close for bar in bars[-days:]]
        return sum(closes, start=_ZERO) / Decimal(days)

    def _cash(self, context: StrategyContext, *, evidence: dict[str, str]) -> TargetPortfolio:
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

        position = context.portfolio.positions.get(self.config.symbol)
        if position is None or context.portfolio.nav <= _ZERO:
            return self._cash(context, evidence=preserved_evidence)

        price = context.reference_prices.get(self.config.symbol)
        if price is None:
            raise ValueError("missing SPY reference price for current position")
        weight = position.quantity * price / context.portfolio.nav
        if weight < _ZERO or weight > _ONE:
            raise ValueError("current SPY weight escaped [0, 1]")

        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={self.config.symbol: weight},
            cash_weight=_ONE - weight,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("0.50"),
            market_state_hash=context.market_state_hash,
            evidence=preserved_evidence,
        )
