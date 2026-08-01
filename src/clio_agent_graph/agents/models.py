"""LLM Agent의 구조화된 출력 계약."""

from typing import Literal

from pydantic import BaseModel, Field


class MatchDecision(BaseModel):
    action: Literal["link_existing", "create_new", "needs_review"]
    issue_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)


class IssueAnalysisOutput(BaseModel):
    issue_id: str
    evidence_counts: dict[str, int]
    root_cause_hypotheses: list[str]
    facts: list[str] = []
    confidence: float = Field(ge=0, le=1)


class ResolutionPlan(BaseModel):
    issue_id: str
    steps: list[str]
    acceptance_criteria: list[str]
    risks: list[str] = []
