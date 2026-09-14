from datetime import UTC, datetime, timedelta
from decimal import Decimal

from project_fifty.domain.models import PortfolioState, Position
from project_fifty.strategies.contracts import MarketBar, StrategyContext
from project_fifty.strategies.m11 import (
    M11_BENCHMARK,
    M11_RESEARCH_SYMBOLS,
    M11_UNIVERSE_VERSION,
    M11OpportunityStrategy,
    M11ScannerConfig,
)


def _bars(
    *,
    start_price: Decimal,
    growth: Decimal,
    volume: Decimal = Decimal("100000"),
    count: int = 30,
) -> tuple[MarketBar, ...]:
    start = datetime(2026, 9, 14, 13, 30, tzinfo=UTC)
    price = start_price
    rows: list[MarketBar] = []
    for index in range(count):
        rows.append(
            MarketBar(
                timestamp=start + timedelta(minutes=5 * index),
                open=price,
                high=price * Decimal("1.0005"),
                low=price * Decimal("0.9995"),
                close=price,
                volume=volume,
            )
        )
        price *= Decimal("1") + growth
    return tuple(rows)


def _context(
    *,
    aapl_growth: Decimal,
    msft_growth: Decimal,
    candidate_volume: Decimal = Decimal("100000"),
) -> StrategyContext:
    spy = _bars(start_price=Decimal("500"), growth=Decimal("0.0001"))
    aapl = _bars(
        start_price=Decimal("200"),
        growth=aapl_growth,
        volume=candidate_volume,
    )
    msft = _bars(
        start_price=Decimal("400"),
        growth=msft_growth,
        volume=candidate_volume,
    )
    as_of = aapl[-1].timestamp
    return StrategyContext(
        as_of=as_of,
        currency="USD",
        portfolio=PortfolioState(
            cash=Decimal("67.6725"),
            positions={},
            nav=Decimal("67.6725"),
            currency="USD",
            as_of=as_of,
        ),
        reference_prices={
            "AAPL": aapl[-1].close,
            "MSFT": msft[-1].close,
            "SPY": spy[-1].close,
        },
        reference_price_timestamps={"AAPL": as_of, "MSFT": as_of, "SPY": as_of},
        market_state_hash="m11-test-state",
        history={"AAPL": aapl, "MSFT": msft, "SPY": spy},
        benchmark_symbol=M11_BENCHMARK,
    )


def test_m11_research_universe_is_versioned_and_excludes_benchmark() -> None:
    assert M11_UNIVERSE_VERSION == "2026-09-14-v1"
    assert 50 <= len(M11_RESEARCH_SYMBOLS) <= 200
    assert "SPY" not in M11_RESEARCH_SYMBOLS
    assert "TQQQ" not in M11_RESEARCH_SYMBOLS
    assert "SQQQ" not in M11_RESEARCH_SYMBOLS


def test_scanner_ranks_stronger_candidate_first_deterministically() -> None:
    strategy = M11OpportunityStrategy(symbols=("MSFT", "AAPL"))
    context = _context(aapl_growth=Decimal("0.004"), msft_growth=Decimal("0.002"))

    ranked = strategy.scan(context)
    target = strategy.generate_target(context)

    assert ranked
    assert ranked[0].symbol == "AAPL"
    assert target.weights == {"AAPL": Decimal("1")}
    assert target.cash_weight == Decimal("0")
    assert target.evidence["selection"] == "ENTER_BEST_LONG"
    assert target.evidence["research_only"] == "true"
    assert target.evidence["signal_family"] in {"momentum", "breakout"}


def test_scanner_rejects_illiquid_candidate() -> None:
    strategy = M11OpportunityStrategy(symbols=("AAPL", "MSFT"))
    context = _context(
        aapl_growth=Decimal("0.004"),
        msft_growth=Decimal("0.003"),
        candidate_volume=Decimal("1"),
    )

    target = strategy.generate_target(context)

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")
    assert target.evidence["selection"] == "CASH_NO_ECONOMIC_OPPORTUNITY"


def test_scanner_rejects_signal_that_does_not_clear_cost_buffer() -> None:
    strategy = M11OpportunityStrategy(symbols=("AAPL", "MSFT"))
    context = _context(aapl_growth=Decimal("0.00015"), msft_growth=Decimal("0.00012"))

    target = strategy.generate_target(context)

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")


def test_equal_candidates_use_symbol_as_stable_tie_breaker() -> None:
    strategy = M11OpportunityStrategy(symbols=("MSFT", "AAPL"))
    base = _context(aapl_growth=Decimal("0.004"), msft_growth=Decimal("0.004"))
    shared = base.history["AAPL"]
    spy = base.history["SPY"]
    context = base.model_copy(
        update={
            "history": {"AAPL": shared, "MSFT": shared, "SPY": spy},
            "reference_prices": {
                "AAPL": shared[-1].close,
                "MSFT": shared[-1].close,
                "SPY": spy[-1].close,
            },
        }
    )

    ranked = strategy.scan(context)

    assert len(ranked) == 2
    assert [item.symbol for item in ranked] == ["AAPL", "MSFT"]


def test_stricter_economic_gate_can_force_cash() -> None:
    config = M11ScannerConfig(
        modeled_round_trip_friction_bps=Decimal("150"),
        minimum_edge_buffer_bps=Decimal("100"),
    )
    strategy = M11OpportunityStrategy(symbols=("AAPL", "MSFT"), config=config)
    context = _context(aapl_growth=Decimal("0.002"), msft_growth=Decimal("0.0015"))

    target = strategy.generate_target(context)

    assert target.weights == {}
    assert target.cash_weight == Decimal("1")


def test_adaptive_engine_can_choose_pullback_mean_reversion() -> None:
    family, edge = M11OpportunityStrategy._best_signal_family(
        short=Decimal("-0.012"),
        medium=Decimal("0.030"),
        relative=Decimal("0.020"),
        breakout=Decimal("-0.010"),
        benchmark_medium=Decimal("0.010"),
    )

    assert family == "pullback_mean_reversion"
    assert edge > 0


def test_adaptive_engine_can_choose_defensive_relative_strength() -> None:
    family, edge = M11OpportunityStrategy._best_signal_family(
        short=Decimal("0.002"),
        medium=Decimal("0.018"),
        relative=Decimal("0.030"),
        breakout=Decimal("-0.005"),
        benchmark_medium=Decimal("-0.012"),
    )

    assert family == "defensive_relative_strength"
    assert edge > 0


def test_rotation_buffer_can_keep_viable_incumbent_instead_of_churning() -> None:
    config = M11ScannerConfig(rotation_buffer_bps=Decimal("10000"))
    strategy = M11OpportunityStrategy(symbols=("AAPL", "MSFT"), config=config)
    base = _context(aapl_growth=Decimal("0.004"), msft_growth=Decimal("0.0035"))
    portfolio = PortfolioState(
        cash=Decimal("27.6725"),
        positions={
            "MSFT": Position(
                symbol="MSFT",
                quantity=Decimal("0.1"),
                average_price=Decimal("400"),
            )
        },
        nav=Decimal("67.6725"),
        currency="USD",
        as_of=base.as_of,
    )
    context = base.model_copy(update={"portfolio": portfolio})

    target = strategy.generate_target(context)

    assert target.weights == {"MSFT": Decimal("1")}
    assert target.evidence["selection"] == "HOLD_INCUMBENT_ROTATION_BUFFER"
