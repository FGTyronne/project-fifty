from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from project_fifty.config.settings import Settings
from project_fifty.domain.models import RejectionReason, RiskDecision, TradeProposal
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.market_data.alpaca import MarketQuote
from project_fifty.market_data.universe import CandidateUniverse
from project_fifty.session.runner import AutonomousSessionRunner, SessionConfig
from project_fifty.strategies.contracts import MarketBar, StrategyContext, TargetPortfolio
from project_fifty.strategies.proposal_builder import ProposalBuilder


class FixedStrategy:
    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={"AAPL": Decimal("0.5")},
            cash_weight=Decimal("0.5"),
            strategy_id="fixed",
            strategy_version="1",
            confidence=Decimal("1"),
            market_state_hash=context.market_state_hash,
        )


class FakeClock:
    def __init__(self, is_open: bool = True) -> None:
        self.is_open = is_open

    def get_clock(self) -> dict[str, object]:
        return {"is_open": self.is_open}


class FakeHandler:
    def __init__(self) -> None:
        self.proposals: list[TradeProposal] = []

    def handle_proposal(self, proposal: TradeProposal):  # type: ignore[no-untyped-def]
        self.proposals.append(proposal)
        return RiskDecision(approved=True, reason=RejectionReason.APPROVED), None


class FakeMarketData:
    def __init__(self, now: datetime, *, stale_quotes: bool = False) -> None:
        self.now = now
        self.stale_quotes = stale_quotes
        self.bar_calls = 0
        start = now - timedelta(minutes=5 * 72)
        self.history: dict[str, tuple[MarketBar, ...]] = {}
        for symbol, price in (("AAPL", Decimal("100")), ("SPY", Decimal("500"))):
            bars: list[MarketBar] = []
            for index in range(70):
                timestamp = start + timedelta(minutes=5 * index)
                bars.append(
                    MarketBar(
                        timestamp=timestamp,
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=Decimal("1000"),
                    )
                )
            self.history[symbol] = tuple(bars)

    def get_bars(
        self,
        symbols: tuple[str, ...],
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "5Min",
        limit: int = 10000,
    ) -> dict[str, tuple[MarketBar, ...]]:
        del start, end, timeframe, limit
        self.bar_calls += 1
        return {symbol: self.history[symbol] for symbol in symbols}

    def get_latest_quotes(self, symbols: tuple[str, ...]) -> dict[str, MarketQuote]:
        quote_time = self.now - timedelta(seconds=10)
        if self.stale_quotes:
            quote_time = self.now - timedelta(minutes=10)
        prices = {"AAPL": Decimal("100"), "SPY": Decimal("500")}
        return {
            symbol: MarketQuote(
                symbol=symbol,
                bid=prices[symbol] - Decimal("0.1"),
                ask=prices[symbol] + Decimal("0.1"),
                timestamp=quote_time,
            )
            for symbol in symbols
        }


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "PROJECT_FIFTY_STARTING_CASH_GBP": Decimal("50"),
            "account_currency": "USD",
            "authorized_starting_cash": Decimal("67.6725"),
            "max_stale_seconds": 60,
            "max_order_notional": Decimal("67.6725"),
            "permitted_symbols": frozenset({"AAPL"}),
        }
    )


def _runner(
    *,
    now: datetime,
    ledger_path: Path,
    market_data: FakeMarketData,
    clock: FakeClock,
    handler: FakeHandler,
) -> AutonomousSessionRunner:
    return AutonomousSessionRunner(
        settings=_settings(),
        universe=CandidateUniverse(symbols=("AAPL",), benchmark_symbol="SPY"),
        market_data=market_data,
        market_clock=clock,
        strategy=FixedStrategy(),
        proposal_builder=ProposalBuilder(estimated_slippage_rate=Decimal("0")),
        proposal_handler=handler,
        ledger=LocalAppendOnlyLedger(ledger_path),
        config=SessionConfig(poll_seconds=1),
    )


def test_session_cycle_generates_risk_routed_proposal_and_persists_bar(tmp_path: Path) -> None:
    now = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    data = FakeMarketData(now)
    handler = FakeHandler()
    ledger_path = tmp_path / "ledger.jsonl"
    runner = _runner(
        now=now,
        ledger_path=ledger_path,
        market_data=data,
        clock=FakeClock(True),
        handler=handler,
    )

    first = runner.run_cycle(now=now)
    restarted = _runner(
        now=now,
        ledger_path=ledger_path,
        market_data=data,
        clock=FakeClock(True),
        handler=handler,
    )
    second = restarted.run_cycle(now=now)

    assert first.market_open is True
    assert first.proposal_count == 1
    assert first.approved_count == 1
    assert len(handler.proposals) == 1
    assert second.skipped_reason == "duplicate_decision_bar"
    assert len(handler.proposals) == 1


def test_stale_quotes_skip_entire_cycle(tmp_path: Path) -> None:
    now = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
    handler = FakeHandler()
    runner = _runner(
        now=now,
        ledger_path=tmp_path / "ledger.jsonl",
        market_data=FakeMarketData(now, stale_quotes=True),
        clock=FakeClock(True),
        handler=handler,
    )

    result = runner.run_cycle(now=now)

    assert result.skipped_reason == "stale_quote"
    assert handler.proposals == []


def test_closed_market_never_fetches_data(tmp_path: Path) -> None:
    now = datetime(2026, 9, 14, 13, 0, tzinfo=UTC)
    data = FakeMarketData(now)
    runner = _runner(
        now=now,
        ledger_path=tmp_path / "ledger.jsonl",
        market_data=data,
        clock=FakeClock(False),
        handler=FakeHandler(),
    )

    result = runner.run_cycle(now=now)

    assert result.skipped_reason == "market_closed"
    assert data.bar_calls == 0
