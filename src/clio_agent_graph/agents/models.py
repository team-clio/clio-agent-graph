"""LLM Agent의 구조화된 출력 계약."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _normalize_confidence(value: float | str) -> float | str:
    if not isinstance(value, str):
        return value
    return {"low": 0.25, "medium": 0.5, "high": 0.8}.get(value.lower(), value)


class MatchDecision(BaseModel):
    action: Literal["link_existing", "create_new", "needs_review"]
    issue_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)

    _normalize_confidence_value = field_validator("confidence", mode="before")(
        _normalize_confidence
    )


class RootCauseHypothesis(BaseModel):
    hypothesis: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = []

    _normalize_confidence_value = field_validator("confidence", mode="before")(
        _normalize_confidence
    )


class VerifiedFact(BaseModel):
    fact: str = Field(min_length=1)
    verified: bool = False


class IssueAnalysisOutput(BaseModel):
    issue_id: str
    evidence_counts: dict[str, int]
    root_cause_hypotheses: list[str | RootCauseHypothesis]
    facts: list[str | VerifiedFact] = []
    confidence: float = Field(ge=0, le=1)

    _normalize_confidence_value = field_validator("confidence", mode="before")(
        _normalize_confidence
    )


class ResolutionPlanStep(BaseModel):
    id: int | str | None = None
    action: str = Field(min_length=1)
    details: str | None = None


class ResolutionRisk(BaseModel):
    risk: str = Field(min_length=1)
    mitigation: str | None = None


class ResolutionPlan(BaseModel):
    issue_id: str
    steps: list[str | ResolutionPlanStep]
    acceptance_criteria: list[str]
    risks: list[str | ResolutionRisk] = []
