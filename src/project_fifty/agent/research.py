from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from project_fifty.strategies.contracts import StrategyContext


class StrictResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchStance(str, Enum):
    SUPPORT = "SUPPORT"
    NEUTRAL = "NEUTRAL"
    OPPOSE = "OPPOSE"


class ResearchEvidence(StrictResearchModel):
    """One researcher's point-in-time evidence for an already selected candidate."""

    researcher: str
    symbol: str
    stance: ResearchStance
    score: Decimal
    thesis: str
    invalidation: str
    observed_at: datetime
    market_state_hash: str
    source_refs: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("score")
    @classmethod
    def _bounded_score(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < Decimal("-1") or value > Decimal("1"):
            raise ValueError("research score must be finite and in [-1, 1]")
        return value

    @model_validator(mode="after")
    def _required_identity(self) -> "ResearchEvidence":
        if not self.researcher or not self.symbol or not self.market_state_hash:
            raise ValueError("researcher, symbol and market_state_hash are required")
        if not self.thesis or not self.invalidation:
            raise ValueError("thesis and invalidation are required")
        return self


class ResearchAssessment(StrictResearchModel):
    """Bounded synthesis for one candidate.

    `conviction_adjustment` can affect strategy composition only. It is never an execution
    instruction and cannot change the candidate universe or constitutional risk limits.
    """

    symbol: str
    conviction_adjustment: Decimal
    confidence: Decimal
    market_state_hash: str
    evidence: tuple[ResearchEvidence, ...]

    @field_validator("conviction_adjustment")
    @classmethod
    def _bounded_adjustment(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < Decimal("-0.25") or value > Decimal("0.25"):
            raise ValueError("conviction adjustment must be finite and in [-0.25, 0.25]")
        return value

    @field_validator("confidence")
    @classmethod
    def _bounded_confidence(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0 or value > 1:
            raise ValueError("research confidence must be finite and in [0, 1]")
        return value

    @model_validator(mode="after")
    def _validate_evidence(self) -> "ResearchAssessment":
        if not self.symbol or not self.market_state_hash:
            raise ValueError("assessment identity is required")
        for item in self.evidence:
            if item.symbol != self.symbol:
                raise ValueError("evidence symbol must match assessment symbol")
            if item.market_state_hash != self.market_state_hash:
                raise ValueError("evidence market state must match assessment market state")
        return self


class ResearchCouncil(Protocol):
    """Optional AI or deterministic research sidecar.

    The caller supplies the candidate set. Implementations may analyse those candidates only.
    """

    def evaluate(
        self,
        *,
        candidates: tuple[str, ...],
        context: StrategyContext,
    ) -> tuple[ResearchAssessment, ...]:
        """Return bounded assessments for the supplied candidate set."""
        ...


def validate_council_output(
    *,
    candidates: tuple[str, ...],
    context: StrategyContext,
    assessments: tuple[ResearchAssessment, ...],
) -> None:
    """Reject agent output that escapes the deterministic candidate or market-state boundary."""

    allowed = set(candidates)
    seen: set[str] = set()
    for assessment in assessments:
        if assessment.symbol not in allowed:
            raise ValueError("research council returned a symbol outside the candidate set")
        if assessment.symbol in seen:
            raise ValueError("research council returned duplicate candidate assessments")
        if assessment.market_state_hash != context.market_state_hash:
            raise ValueError("research council output is stale")
        seen.add(assessment.symbol)
