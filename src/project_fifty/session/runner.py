from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Callable, Protocol

from project_fifty.config.settings import Settings
from project_fifty.domain.models import ExecutionReport, PortfolioState, RiskDecision, TradeProposal
from project_fifty.ledger.base import Ledger
from project_fifty.market_data.alpaca import MarketQuote
from project_fifty.market_data.state import market_state_hash
from project_fifty.market_data.universe import CandidateUniverse
from project_fifty.portfolio.reconcile import PortfolioReconciler
from project_fifty.strategies.contracts import MarketBar, StrategyContext, StrategyProvider
from project_fifty.strategies.proposal_builder import ProposalBuilder


class MarketDataProvider(Protocol):
    def get_bars(
        self,
        symbols: tuple[str, ...],
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "5Min",
        limit: int = 10000,
    ) -> dict[str, tuple[MarketBar, ...]]: ...

    def get_latest_quotes(self, symbols: tuple[str, ...]) -> dict[str, MarketQuote]: ...


class MarketClockProvider(Protocol):
    def get_clock(self) -> dict[str, object]: ...


class ProposalHandler(Protocol):
    def handle_proposal(
        self,
        proposal: TradeProposal,
    ) -> tuple[RiskDecision, ExecutionReport | None]: ...


@dataclass(frozen=True)
class SessionConfig:
    timeframe: str = "5Min"
    timeframe_seconds: int = 300
    history_days: int = 14
    poll_seconds: int = 60

    def __post_init__(self) -> None:
        if min(self.timeframe_seconds, self.history_days, self.poll_seconds) <= 0:
            raise ValueError("session timing values must be positive")


@dataclass(frozen=True)
class SessionCycleResult:
    market_open: bool
    decision_bar_time: datetime | None
    market_state_hash: str | None
    proposal_count: int
    approved_count: int
    rejected_count: int
    skipped_reason: str | None = None


class AutonomousSessionRunner:
    """Run one deterministic decision cycle at a time while the market is open.

    The runner owns no broker credentials and cannot bypass the proposal/risk/kernel path. Market
    data and broker clock are read-only inputs. Every actual order still enters through
    `ProposalHandler`, normally Project Fifty's ExecutionKernel.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        universe: CandidateUniverse,
        market_data: MarketDataProvider,
        market_clock: MarketClockProvider,
        strategy: StrategyProvider,
        proposal_builder: ProposalBuilder,
        proposal_handler: ProposalHandler,
        ledger: Ledger,
        config: SessionConfig | None = None,
    ) -> None:
        self._settings = settings
        self._universe = universe
        self._market_data = market_data
        self._market_clock = market_clock
        self._strategy = strategy
        self._proposal_builder = proposal_builder
        self._proposal_handler = proposal_handler
        self._ledger = ledger
        self._config = config or SessionConfig()

    def run_cycle(self, *, now: datetime | None = None) -> SessionCycleResult:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        clock = self._market_clock.get_clock()
        if not bool(clock.get("is_open")):
            return SessionCycleResult(
                market_open=False,
                decision_bar_time=None,
                market_state_hash=None,
                proposal_count=0,
                approved_count=0,
                rejected_count=0,
                skipped_reason="market_closed",
            )

        provisional = self._authorized_portfolio_with_fill_marks()
        symbols = tuple(
            sorted(set(self._universe.all_symbols) | set(provisional.positions))
        )
        end = current - timedelta(seconds=self._config.timeframe_seconds)
        start = end - timedelta(days=self._config.history_days)
        history = self._market_data.get_bars(
            symbols,
            start=start,
            end=end,
            timeframe=self._config.timeframe,
        )
        benchmark_bars = history.get(self._universe.benchmark_symbol, ())
        if not benchmark_bars:
            return self._skip(current, "missing_benchmark_history")
        decision_bar_time = benchmark_bars[-1].timestamp
        if self._last_completed_bar() == decision_bar_time:
            return SessionCycleResult(
                market_open=True,
                decision_bar_time=decision_bar_time,
                market_state_hash=None,
                proposal_count=0,
                approved_count=0,
                rejected_count=0,
                skipped_reason="duplicate_decision_bar",
            )

        quotes = self._market_data.get_latest_quotes(symbols)
        missing_quotes = set(symbols) - set(quotes)
        if missing_quotes:
            return self._skip(current, "missing_quote")
        if any(quote.timestamp > current for quote in quotes.values()):
            return self._skip(current, "future_quote")
        if any(
            (current - quote.timestamp).total_seconds() > self._settings.max_stale_seconds
            for quote in quotes.values()
        ):
            return self._skip(current, "stale_quote")
        if any(not quote.is_actionable for quote in quotes.values()):
            return self._skip(current, "non_actionable_quote")

        mark_prices = {symbol: quote.midpoint for symbol, quote in quotes.items()}
        portfolio = self._authorized_portfolio(mark_prices)
        state_hash = market_state_hash(history=history, quotes=quotes)
        context = StrategyContext(
            as_of=current,
            currency=self._settings.account_currency,
            portfolio=portfolio,
            reference_prices=mark_prices,
            reference_price_timestamps={
                symbol: quote.timestamp for symbol, quote in quotes.items()
            },
            market_state_hash=state_hash,
            history=history,
            benchmark_symbol=self._universe.benchmark_symbol,
        )
        target = self._strategy.generate_target(context)
        proposals = self._proposal_builder.build(target=target, context=context)

        approved = 0
        rejected = 0
        for proposal in proposals:
            decision, _ = self._proposal_handler.handle_proposal(proposal)
            if decision.approved:
                approved += 1
            else:
                rejected += 1

        self._ledger.append(
            "strategy_cycle_completed",
            {
                "as_of": current.isoformat(),
                "decision_bar_time": decision_bar_time.isoformat(),
                "market_state_hash": state_hash,
                "strategy_id": target.strategy_id,
                "strategy_version": target.strategy_version,
                "proposal_count": len(proposals),
                "approved_count": approved,
                "rejected_count": rejected,
            },
        )
        return SessionCycleResult(
            market_open=True,
            decision_bar_time=decision_bar_time,
            market_state_hash=state_hash,
            proposal_count=len(proposals),
            approved_count=approved,
            rejected_count=rejected,
        )

    def run_until_close(
        self,
        *,
        max_cycles: int | None = None,
        now_provider: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> tuple[SessionCycleResult, ...]:
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("max_cycles must be positive when supplied")
        clock = now_provider or (lambda: datetime.now(UTC))
        results: list[SessionCycleResult] = []
        while True:
            result = self.run_cycle(now=clock())
            results.append(result)
            if not result.market_open:
                break
            if max_cycles is not None and len(results) >= max_cycles:
                break
            sleeper(float(self._config.poll_seconds))
        return tuple(results)

    def _authorized_portfolio_with_fill_marks(self) -> PortfolioState:
        reports = self._execution_reports()
        mark_prices: dict[str, Decimal] = {}
        for report in reports:
            if report.fill_price > 0:
                mark_prices[report.symbol] = report.fill_price
        return PortfolioReconciler.replay_events(
            starting_cash=self._settings.authorized_starting_cash,
            events=reports,
            mark_prices=mark_prices,
            currency=self._settings.account_currency,
        )

    def _authorized_portfolio(self, mark_prices: dict[str, Decimal]) -> PortfolioState:
        return PortfolioReconciler.replay_events(
            starting_cash=self._settings.authorized_starting_cash,
            events=self._execution_reports(),
            mark_prices=mark_prices,
            currency=self._settings.account_currency,
        )

    def _execution_reports(self) -> list[ExecutionReport]:
        return [
            ExecutionReport.model_validate(event.payload)
            for event in self._ledger.all_events()
            if event.event_type == "broker_execution_report"
        ]

    def _last_completed_bar(self) -> datetime | None:
        for event in reversed(self._ledger.all_events()):
            if event.event_type != "strategy_cycle_completed":
                continue
            value = event.payload.get("decision_bar_time")
            if isinstance(value, str):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    return parsed.astimezone(UTC)
        return None

    def _skip(self, now: datetime, reason: str) -> SessionCycleResult:
        self._ledger.append(
            "strategy_cycle_skipped",
            {"as_of": now.isoformat(), "reason": reason},
        )
        return SessionCycleResult(
            market_open=True,
            decision_bar_time=None,
            market_state_hash=None,
            proposal_count=0,
            approved_count=0,
            rejected_count=0,
            skipped_reason=reason,
        )
