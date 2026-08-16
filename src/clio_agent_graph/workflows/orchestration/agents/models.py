"""LLM Agent의 구조화된 출력 계약."""

import re
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


def _normalize_confidence(value: float | str) -> float | str:
    if not isinstance(value, str):
        return value
    return {"low": 0.25, "medium": 0.5, "high": 0.8}.get(value.lower(), value)


MAX_LONG_ID = 9_223_372_036_854_775_807


class MatchDecision(BaseModel):
    """리포트를 기존 이슈에 연결할지 결정한 Agent의 최종 판단."""

    action: Literal["link_existing", "create_new", "needs_review"]
    issue_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)

    _normalize_confidence_value = field_validator("confidence", mode="before")(
        _normalize_confidence
    )

    @model_validator(mode="after")
    def validate_issue_id(self) -> "MatchDecision":
        if self.action == "link_existing" and (
            self.issue_id is None
            or not self.issue_id.isdigit()
            or not 0 < int(self.issue_id) <= MAX_LONG_ID
        ):
            raise ValueError("link_existing requires a positive numeric issue_id")
        return self


class KoreanIssueDraft(BaseModel):
    """신규 Issue에 저장할 한국어 제목과 상세 Markdown 설명."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def require_korean_title(cls, value: str) -> str:
        if not re.search(r"[가-힣]", value):
            raise ValueError("Issue title must contain Korean text")
        return value

    @field_validator("description")
    @classmethod
    def require_description_template(cls, value: str) -> str:
        headings = (
            "## 증상",
            "## 기대 동작",
            "## 재현 절차",
            "## 영향 범위",
            "## 오류 신호",
            "## 조사 메모",
        )
        if any(heading not in value for heading in headings):
            raise ValueError("Issue description must include every required Korean section")
        return value


class RootCauseHypothesis(BaseModel):
    """확신도와 근거를 함께 보존하는 원인 가설."""

    hypothesis: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = []

    _normalize_confidence_value = field_validator("confidence", mode="before")(
        _normalize_confidence
    )


class VerifiedFact(BaseModel):
    """분석 과정에서 검증 여부를 명시한 사실 후보."""

    fact: str = Field(
        min_length=1,
        validation_alias=AliasChoices("fact", "claim", "statement"),
    )
    verified: bool = False


class EvidenceCitation(BaseModel):
    """분석 결과가 참조한 고정 PCM snapshot의 근거."""

    source_type: str = "knowledge"
    source_id: str | None = None
    source_revision: str | None = None
    knowledge_id: str | None = None
    knowledge_revision: int | None = Field(default=None, ge=1)
    repository_id: str | None = None
    commit: str | None = None
    evidence_id: str | None = None
    file_path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    location: str | None = None
    snippet: str | None = None
    observation: str | None = None

    @model_validator(mode="after")
    def validate_code_location(self) -> "EvidenceCitation":
        if self.end_line is not None and self.start_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class IssueAnalysisOutput(BaseModel):
    """이슈 조사 Agent가 Quality Gate에 제출하는 구조화된 분석."""

    issue_id: str
    evidence_counts: dict[str, int]
    root_cause_hypotheses: list[str | RootCauseHypothesis]
    facts: list[str | VerifiedFact] = []
    citations: list[EvidenceCitation] = []
    confidence: float = Field(ge=0, le=1)

    _normalize_confidence_value = field_validator("confidence", mode="before")(
        _normalize_confidence
    )


class ResolutionPlanStep(BaseModel):
    """구현 순서와 상세 작업을 표현하는 해결 계획의 한 단계."""

    id: int | str | None = None
    action: str = Field(min_length=1)
    details: str | None = None


class ResolutionRisk(BaseModel):
    """해결 과정에서 예상되는 위험과 선택적 완화책."""

    risk: str = Field(min_length=1)
    mitigation: str | None = None


class ResolutionPlan(BaseModel):
    """검증 가능한 완료 조건과 위험을 포함한 이슈 해결 계획."""

    issue_id: str
    steps: list[str | ResolutionPlanStep]
    acceptance_criteria: list[str]
    risks: list[str | ResolutionRisk] = []
