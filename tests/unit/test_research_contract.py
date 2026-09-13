from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from project_fifty.agent.research import (
    ResearchAssessment,
    ResearchEvidence,
    ResearchStance,
    validate_council_output,
)
from project_fifty.domain.models import PortfolioState
from project_fifty.strategies.contracts import StrategyContext


def _context() -> StrategyContext:
    as_of = datetime(2026, 9, 14, 15, 0, tzinfo=UTC)
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
        reference_prices={"AAPL": Decimal("100")},
        reference_price_timestamps={"AAPL": as_of},
        market_state_hash="market-1",
    )


def _evidence(symbol: str = "AAPL", state: str = "market-1") -> ResearchEvidence:
    return ResearchEvidence(
        researcher="bear-researcher",
        symbol=symbol,
        stance=ResearchStance.OPPOSE,
        score=Decimal("-0.4"),
        thesis="Recent acceleration increases reversal risk.",
        invalidation="Trend persists with improving breadth.",
        observed_at=datetime(2026, 9, 14, 15, 0, tzinfo=UTC),
        market_state_hash=state,
        source_refs=("price-bars",),
    )


def test_research_adjustment_cannot_exceed_bound() -> None:
    with pytest.raises(ValidationError, match="conviction adjustment"):
        ResearchAssessment(
            symbol="AAPL",
            conviction_adjustment=Decimal("0.30"),
            confidence=Decimal("0.8"),
            market_state_hash="market-1",
            evidence=(_evidence(),),
        )


def test_research_council_cannot_invent_symbol() -> None:
    context = _context()
    assessment = ResearchAssessment(
        symbol="TSLA",
        conviction_adjustment=Decimal("0.10"),
        confidence=Decimal("0.7"),
        market_state_hash="market-1",
        evidence=(_evidence(symbol="TSLA"),),
    )

    with pytest.raises(ValueError, match="outside the candidate set"):
        validate_council_output(
            candidates=("AAPL",),
            context=context,
            assessments=(assessment,),
        )


def test_research_council_rejects_stale_market_state() -> None:
    context = _context()
    assessment = ResearchAssessment(
        symbol="AAPL",
        conviction_adjustment=Decimal("-0.10"),
        confidence=Decimal("0.7"),
        market_state_hash="old-market",
        evidence=(_evidence(state="old-market"),),
    )

    with pytest.raises(ValueError, match="stale"):
        validate_council_output(
            candidates=("AAPL",),
            context=context,
            assessments=(assessment,),
        )
