from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio

M11_STRATEGY_ID = "multi-asset-opportunity-scanner"
M11_STRATEGY_VERSION = "0.1.0-research"
M11_UNIVERSE_VERSION = "2026-09-14-v1"
M11_BENCHMARK = "SPY"

# Research-only, deterministic initial universe. Every name must still pass broker metadata checks
# before any future paper deployment. Leveraged/inverse ETFs, derivatives and shorting are excluded.
M11_RESEARCH_SYMBOLS: tuple[str, ...] = (
    "AAPL",
    "ABBV",
    "ABNB",
    "ADBE",
    "AMD",
    "AMAT",
    "AMGN",
    "AMZN",
    "AVGO",
    "BAC",
    "BRK.B",
    "CAT",
    "CMCSA",
    "COIN",
    "CRM",
    "CRWD",
    "CSCO",
    "CVX",
    "DIA",
    "DIS",
    "GE",
    "GLD",
    "GM",
    "GOOGL",
    "GS",
    "HD",
    "IBM",
    "INTC",
    "IWM",
    "JNJ",
    "JPM",
    "KO",
    "LLY",
    "LMT",
    "MA",
    "META",
    "MRK",
    "MS",
    "MSFT",
    "MU",
    "NFLX",
    "NOW",
    "NVDA",
    "ORCL",
    "PANW",
    "PEP",
    "PFE",
    "PLTR",
    "PYPL",
    "QCOM",
    "QQQ",
    "SLV",
    "SMH",
    "T",
    "TLT",
    "TSLA",
    "UNH",
    "V",
    "WFC",
    "WMT",
    "XBI",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
    "XOM",
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TEN_THOUSAND = Decimal("10000")


@dataclass(frozen=True)
class M11ScannerConfig:
    """Predeclared first-pass M11 research parameters.

    These parameters are intentionally simple and deterministic. They are a research starting point,
    not a profitability claim and not paper-trading authority.
    """

    short_momentum_bars: int = 3
    medium_momentum_bars: int = 12
    breakout_bars: int = 24
    volatility_bars: int = 20
    volume_bars: int = 20
    minimum_average_dollar_volume: Decimal = Decimal("1000000")
    modeled_round_trip_friction_bps: Decimal = Decimal("20")
    minimum_edge_buffer_bps: Decimal = Decimal("10")
    minimum_score: Decimal = Decimal("0.75")
    volatility_floor: Decimal = Decimal("0.0005")

    def __post_init__(self) -> None:
        windows = (
            self.short_momentum_bars,
            self.medium_momentum_bars,
            self.breakout_bars,
            self.volatility_bars,
            self.volume_bars,
        )
        if min(windows) <= 0:
            raise ValueError("M11 lookback windows must be positive")
        decimals = (
            self.minimum_average_dollar_volume,
            self.modeled_round_trip_friction_bps,
            self.minimum_edge_buffer_bps,
            self.minimum_score,
            self.volatility_floor,
        )
        if any(not value.is_finite() or value < 0 for value in decimals):
            raise ValueError("M11 numeric gates must be finite and non-negative")
        if self.volatility_floor == 0:
            raise ValueError("M11 volatility floor must be positive")


@dataclass(frozen=True)
class OpportunityCandidate:
    symbol: str
    score: Decimal
    gross_edge_bps: Decimal
    estimated_net_edge_bps: Decimal
    average_dollar_volume: Decimal
    short_momentum: Decimal
    medium_momentum: Decimal
    relative_strength: Decimal
    breakout_return: Decimal
    realised_volatility: Decimal

    def evidence(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "score": str(self.score),
            "gross_edge_bps": str(self.gross_edge_bps),
            "estimated_net_edge_bps": str(self.estimated_net_edge_bps),
            "average_dollar_volume": str(self.average_dollar_volume),
            "short_momentum": str(self.short_momentum),
            "medium_momentum": str(self.medium_momentum),
            "relative_strength": str(self.relative_strength),
            "breakout_return": str(self.breakout_return),
            "realised_volatility": str(self.realised_volatility),
        }


class M11OpportunityStrategy:
    """Research-only cross-sectional opportunity scanner.

    The strategy selects at most one long candidate or cash. It has no broker credentials and cannot
    bypass Project Fifty's proposal/risk/execution boundary. M11 is intentionally not wired into the
    M10 paper workflow.
    """

    strategy_id = M11_STRATEGY_ID
    strategy_version = M11_STRATEGY_VERSION

    def __init__(
        self,
        *,
        symbols: tuple[str, ...] = M11_RESEARCH_SYMBOLS,
        config: M11ScannerConfig | None = None,
    ) -> None:
        normalized = tuple(sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()}))
        if not normalized:
            raise ValueError("M11 research universe must not be empty")
        if M11_BENCHMARK in normalized:
            raise ValueError("SPY is the M11 benchmark and must not also be a candidate")
        self._symbols = normalized
        self.config = config or M11ScannerConfig()

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    def scan(self, context: StrategyContext) -> tuple[OpportunityCandidate, ...]:
        if context.benchmark_symbol != M11_BENCHMARK:
            raise ValueError("M11 requires SPY as benchmark")
        benchmark = context.history.get(M11_BENCHMARK, ())
        if not self._enough_history(benchmark):
            return ()
        benchmark_medium = self._return(benchmark, self.config.medium_momentum_bars)

        candidates: list[OpportunityCandidate] = []
        for symbol in self._symbols:
            bars = context.history.get(symbol, ())
            if not self._enough_history(bars):
                continue
            candidate = self._candidate(symbol, bars, benchmark_medium)
            if candidate is None:
                continue
            candidates.append(candidate)

        return tuple(sorted(candidates, key=lambda item: (-item.score, item.symbol)))

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        ranked = self.scan(context)
        common = {
            "universe_version": M11_UNIVERSE_VERSION,
            "candidate_count": str(len(ranked)),
            "modeled_round_trip_friction_bps": str(
                self.config.modeled_round_trip_friction_bps
            ),
            "minimum_edge_buffer_bps": str(self.config.minimum_edge_buffer_bps),
            "research_only": "true",
        }
        if not ranked:
            return TargetPortfolio(
                as_of=context.as_of,
                currency=context.currency,
                weights={},
                cash_weight=_ONE,
                strategy_id=self.strategy_id,
                strategy_version=self.strategy_version,
                confidence=Decimal("0.50"),
                market_state_hash=context.market_state_hash,
                evidence={**common, "selection": "CASH_NO_ECONOMIC_OPPORTUNITY"},
            )

        best = ranked[0]
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={best.symbol: _ONE},
            cash_weight=_ZERO,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("0.50"),
            market_state_hash=context.market_state_hash,
            evidence={**common, "selection": "ENTER_BEST_LONG", **best.evidence()},
        )

    def _candidate(
        self,
        symbol: str,
        bars: tuple[MarketBar, ...],
        benchmark_medium: Decimal,
    ) -> OpportunityCandidate | None:
        short = self._return(bars, self.config.short_momentum_bars)
        medium = self._return(bars, self.config.medium_momentum_bars)
        relative = medium - benchmark_medium
        prior = bars[-(self.config.breakout_bars + 1) : -1]
        prior_high = max(bar.high for bar in prior)
        breakout = bars[-1].close / prior_high - _ONE
        volatility = self._average_absolute_return(bars, self.config.volatility_bars)
        dollar_volume = self._average_dollar_volume(bars, self.config.volume_bars)
        if dollar_volume < self.config.minimum_average_dollar_volume:
            return None

        # Weighted gross directional opportunity. Breakout contributes only when price has actually
        # exceeded its prior range; negative breakout values do not create a synthetic long edge.
        positive_breakout = max(breakout, _ZERO)
        gross_edge = (
            Decimal("0.35") * short
            + Decimal("0.35") * medium
            + Decimal("0.20") * relative
            + Decimal("0.10") * positive_breakout
        )
        gross_edge_bps = gross_edge * _TEN_THOUSAND
        required_bps = (
            self.config.modeled_round_trip_friction_bps + self.config.minimum_edge_buffer_bps
        )
        if gross_edge_bps < required_bps:
            return None

        denominator = max(volatility, self.config.volatility_floor)
        score = gross_edge / denominator
        if score < self.config.minimum_score:
            return None

        return OpportunityCandidate(
            symbol=symbol,
            score=score,
            gross_edge_bps=gross_edge_bps,
            estimated_net_edge_bps=(
                gross_edge_bps - self.config.modeled_round_trip_friction_bps
            ),
            average_dollar_volume=dollar_volume,
            short_momentum=short,
            medium_momentum=medium,
            relative_strength=relative,
            breakout_return=breakout,
            realised_volatility=volatility,
        )

    def _enough_history(self, bars: tuple[MarketBar, ...]) -> bool:
        required = max(
            self.config.short_momentum_bars + 1,
            self.config.medium_momentum_bars + 1,
            self.config.breakout_bars + 1,
            self.config.volatility_bars + 1,
            self.config.volume_bars,
        )
        return len(bars) >= required

    @staticmethod
    def _return(bars: tuple[MarketBar, ...], lookback: int) -> Decimal:
        return bars[-1].close / bars[-(lookback + 1)].close - _ONE

    @staticmethod
    def _average_absolute_return(bars: tuple[MarketBar, ...], window: int) -> Decimal:
        recent = bars[-(window + 1) :]
        moves = [
            abs(recent[index].close / recent[index - 1].close - _ONE)
            for index in range(1, len(recent))
        ]
        return sum(moves, start=_ZERO) / Decimal(len(moves))

    @staticmethod
    def _average_dollar_volume(bars: tuple[MarketBar, ...], window: int) -> Decimal:
        recent = bars[-window:]
        values = [bar.close * bar.volume for bar in recent]
        return sum(values, start=_ZERO) / Decimal(len(values))
