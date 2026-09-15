from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio

M11_STRATEGY_ID = "multi-asset-opportunity-scanner"
M11_STRATEGY_VERSION = "0.3.0-research"
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
_NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class M11ScannerConfig:
    """Predeclared M11 adaptive intraday research parameters.

    The strategy may choose among multiple signal families, rotate between qualifying assets and
    exit positions during the session. It is explicitly day-trading research: new entries stop late
    in the session and all exposure is targeted back to cash before the regular close. These values
    are research parameters, not profitability claims or live-money authority.
    """

    short_momentum_bars: int = 3
    medium_momentum_bars: int = 12
    breakout_bars: int = 24
    volatility_bars: int = 20
    volume_bars: int = 20
    minimum_average_dollar_volume: Decimal = Decimal("1000000")
    modeled_round_trip_friction_bps: Decimal = Decimal("20")
    minimum_edge_buffer_bps: Decimal = Decimal("10")
    rotation_buffer_bps: Decimal = Decimal("12")
    minimum_score: Decimal = Decimal("0.75")
    volatility_floor: Decimal = Decimal("0.0005")
    stop_loss_bps: Decimal = Decimal("75")
    take_profit_bps: Decimal = Decimal("125")
    entry_cutoff_minutes_before_close: int = 45
    flatten_minutes_before_close: int = 15

    def __post_init__(self) -> None:
        windows = (
            self.short_momentum_bars,
            self.medium_momentum_bars,
            self.breakout_bars,
            self.volatility_bars,
            self.volume_bars,
            self.entry_cutoff_minutes_before_close,
            self.flatten_minutes_before_close,
        )
        if min(windows) <= 0:
            raise ValueError("M11 lookback and session timing values must be positive")
        if self.flatten_minutes_before_close > self.entry_cutoff_minutes_before_close:
            raise ValueError("flatten window must not begin before the entry cutoff")
        decimals = (
            self.minimum_average_dollar_volume,
            self.modeled_round_trip_friction_bps,
            self.minimum_edge_buffer_bps,
            self.rotation_buffer_bps,
            self.minimum_score,
            self.volatility_floor,
            self.stop_loss_bps,
            self.take_profit_bps,
        )
        if any(not value.is_finite() or value < 0 for value in decimals):
            raise ValueError("M11 numeric gates must be finite and non-negative")
        if self.volatility_floor == 0:
            raise ValueError("M11 volatility floor must be positive")
        if self.stop_loss_bps == 0 or self.take_profit_bps == 0:
            raise ValueError("M11 stop loss and take profit must be positive")


@dataclass(frozen=True)
class OpportunityCandidate:
    symbol: str
    signal_family: str
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
            "signal_family": self.signal_family,
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
    """Adaptive, day-trading-oriented cross-sectional opportunity scanner.

    The engine scans many permitted assets and lets the strongest qualifying signal family win. It
    can enter, hold, rotate, stop out, take profit or return to cash. It explicitly targets no
    overnight exposure. It has no broker credentials and cannot bypass Project Fifty's proposal,
    risk and execution boundary.
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
        common = self._common_evidence()
        held_symbols = self._held_symbols(context)

        if self._flatten_window(context.as_of):
            return self._cash_target(context, common, "FLATTEN_END_OF_DAY")

        if len(held_symbols) > 1:
            return self._cash_target(context, common, "FLATTEN_UNSUPPORTED_MULTI_POSITION")

        if held_symbols:
            risk_exit = self._risk_exit_reason(context, held_symbols[0])
            if risk_exit is not None:
                return self._cash_target(context, common, risk_exit)

        ranked = self.scan(context)
        common["candidate_count"] = str(len(ranked))

        if self._entry_cutoff_window(context.as_of):
            if not held_symbols:
                return self._cash_target(context, common, "CASH_ENTRY_CUTOFF")
            incumbent_symbol = held_symbols[0]
            incumbent = next(
                (candidate for candidate in ranked if candidate.symbol == incumbent_symbol),
                None,
            )
            if incumbent is None:
                return self._cash_target(
                    context,
                    common,
                    "EXIT_SIGNAL_INVALIDATED_ENTRY_CUTOFF",
                )
            return self._hold_current_position_target(
                context,
                common,
                incumbent_symbol,
                "HOLD_INCUMBENT_ENTRY_CUTOFF",
                incumbent,
            )

        if not ranked:
            selection = (
                "EXIT_NO_ECONOMIC_OPPORTUNITY" if held_symbols else "CASH_NO_ECONOMIC_OPPORTUNITY"
            )
            return self._cash_target(context, common, selection)

        selected, selection = self._select_with_incumbency(ranked, context)
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={selected.symbol: _ONE},
            cash_weight=_ZERO,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("0.50"),
            market_state_hash=context.market_state_hash,
            evidence={**common, "selection": selection, **selected.evidence()},
        )

    def _common_evidence(self) -> dict[str, str]:
        return {
            "universe_version": M11_UNIVERSE_VERSION,
            "candidate_count": "0",
            "modeled_round_trip_friction_bps": str(
                self.config.modeled_round_trip_friction_bps
            ),
            "minimum_edge_buffer_bps": str(self.config.minimum_edge_buffer_bps),
            "rotation_buffer_bps": str(self.config.rotation_buffer_bps),
            "stop_loss_bps": str(self.config.stop_loss_bps),
            "take_profit_bps": str(self.config.take_profit_bps),
            "entry_cutoff_minutes_before_close": str(
                self.config.entry_cutoff_minutes_before_close
            ),
            "flatten_minutes_before_close": str(self.config.flatten_minutes_before_close),
            "day_trade_only": "true",
            "research_only": "true",
        }

    def _cash_target(
        self,
        context: StrategyContext,
        common: dict[str, str],
        selection: str,
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
            evidence={**common, "selection": selection},
        )

    def _hold_current_position_target(
        self,
        context: StrategyContext,
        common: dict[str, str],
        symbol: str,
        selection: str,
        candidate: OpportunityCandidate,
    ) -> TargetPortfolio:
        position = context.portfolio.positions[symbol]
        price = context.reference_prices[symbol]
        if context.portfolio.nav <= 0:
            return self._cash_target(context, common, "FLATTEN_INVALID_NAV")
        current_weight = (position.quantity * price) / context.portfolio.nav
        current_weight = max(_ZERO, min(_ONE, current_weight))
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={symbol: current_weight},
            cash_weight=_ONE - current_weight,
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("0.50"),
            market_state_hash=context.market_state_hash,
            evidence={**common, "selection": selection, **candidate.evidence()},
        )

    def _risk_exit_reason(self, context: StrategyContext, symbol: str) -> str | None:
        position = context.portfolio.positions[symbol]
        current_price = context.reference_prices.get(symbol)
        if current_price is None or position.average_price <= 0:
            return "FLATTEN_MISSING_POSITION_MARK"
        pnl_bps = (current_price / position.average_price - _ONE) * _TEN_THOUSAND
        if pnl_bps <= -self.config.stop_loss_bps:
            return "STOP_LOSS_EXIT"
        if pnl_bps >= self.config.take_profit_bps:
            return "TAKE_PROFIT_EXIT"
        return None

    def _select_with_incumbency(
        self,
        ranked: tuple[OpportunityCandidate, ...],
        context: StrategyContext,
    ) -> tuple[OpportunityCandidate, str]:
        best = ranked[0]
        held_symbols = self._held_symbols(context)
        if len(held_symbols) != 1:
            return best, "ENTER_BEST_LONG"

        incumbent_symbol = held_symbols[0]
        incumbent = next(
            (candidate for candidate in ranked if candidate.symbol == incumbent_symbol),
            None,
        )
        if incumbent is None:
            return best, "ROTATE_FROM_INVALIDATED_LONG"
        if incumbent.symbol == best.symbol:
            return best, "HOLD_BEST_LONG"

        challenger_threshold = incumbent.estimated_net_edge_bps + self.config.rotation_buffer_bps
        if best.estimated_net_edge_bps < challenger_threshold:
            return incumbent, "HOLD_INCUMBENT_ROTATION_BUFFER"
        return best, "ROTATE_TO_BETTER_LONG"

    @staticmethod
    def _held_symbols(context: StrategyContext) -> tuple[str, ...]:
        return tuple(
            sorted(
                symbol
                for symbol, position in context.portfolio.positions.items()
                if position.quantity > 0
            )
        )

    def _entry_cutoff_window(self, as_of: datetime) -> bool:
        return self._minutes_to_regular_close(as_of) <= self.config.entry_cutoff_minutes_before_close

    def _flatten_window(self, as_of: datetime) -> bool:
        return self._minutes_to_regular_close(as_of) <= self.config.flatten_minutes_before_close

    @staticmethod
    def _minutes_to_regular_close(as_of: datetime) -> int:
        if as_of.tzinfo is None:
            raise ValueError("M11 requires timezone-aware timestamps")
        local = as_of.astimezone(_NEW_YORK)
        close = local.replace(hour=16, minute=0, second=0, microsecond=0)
        remaining = int((close - local).total_seconds() // 60)
        return max(0, remaining)

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

        signal_family, gross_edge = self._best_signal_family(
            short=short,
            medium=medium,
            relative=relative,
            breakout=breakout,
            benchmark_medium=benchmark_medium,
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
            signal_family=signal_family,
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

    @staticmethod
    def _best_signal_family(
        *,
        short: Decimal,
        medium: Decimal,
        relative: Decimal,
        breakout: Decimal,
        benchmark_medium: Decimal,
    ) -> tuple[str, Decimal]:
        positive_short = max(short, _ZERO)
        positive_medium = max(medium, _ZERO)
        positive_relative = max(relative, _ZERO)
        positive_breakout = max(breakout, _ZERO)

        families: list[tuple[str, Decimal]] = [
            (
                "momentum",
                Decimal("0.35") * short
                + Decimal("0.35") * medium
                + Decimal("0.20") * relative
                + Decimal("0.10") * positive_breakout,
            ),
            (
                "breakout",
                Decimal("0.50") * positive_breakout
                + Decimal("0.30") * positive_short
                + Decimal("0.20") * positive_relative,
            ),
        ]

        if medium > 0 and short < 0:
            families.append(
                (
                    "pullback_mean_reversion",
                    Decimal("0.55") * (-short)
                    + Decimal("0.25") * positive_medium
                    + Decimal("0.20") * positive_relative,
                )
            )

        if benchmark_medium < 0 and medium > 0:
            families.append(
                (
                    "defensive_relative_strength",
                    Decimal("0.45") * positive_medium
                    + Decimal("0.45") * positive_relative
                    + Decimal("0.10") * positive_short,
                )
            )

        return sorted(families, key=lambda item: (-item[1], item[0]))[0]

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
