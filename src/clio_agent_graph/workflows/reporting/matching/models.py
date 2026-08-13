"""Report Matcher와 RAG 하위 에이전트가 공유하는 데이터 계약."""

from enum import StrEnum

from pydantic import Field, model_validator

from clio_agent_graph.workflows.reporting.normalization.models import (
    ContractModel,
    NonEmptyText,
    NormalizedReport,
)


class RepresentativeBug(ContractModel):
    """Issue의 실제 발생 사례를 보여주는 대표 Bug."""

    bug_id: int = Field(gt=0)
    normalized_report: NormalizedReport


class IssueCandidate(ContractModel):
    """RAG 하위 에이전트가 RM에 전달하는 기존 Issue 후보."""

    issue_id: int = Field(gt=0)
    title: NonEmptyText | None = None
    summary: NonEmptyText | None = None
    status: NonEmptyText | None = None
    retrieval_score: float = Field(ge=0.0, le=1.0)
    retrieval_reasons: list[NonEmptyText] = Field(default_factory=list)
    representative_bugs: list[RepresentativeBug] = Field(
        default_factory=list,
        max_length=3,
    )

    @model_validator(mode="after")
    def require_comparable_content(self) -> "IssueCandidate":
        """제목·요약·대표 Bug가 모두 없는 빈 후보를 거부한다."""

        if self.title is None and self.summary is None and not self.representative_bugs:
            raise ValueError("Issue candidate must contain comparable content.")
        return self


class IssueRetrievalRequest(ContractModel):
    """RM이 RAG 하위 에이전트에 보내는 후보 검색 요청."""

    project_id: int = Field(gt=0)
    bug_id: int = Field(gt=0)
    normalized_report: NormalizedReport


class IssueRetrievalResponse(ContractModel):
    """RAG 하위 에이전트가 순위 순서대로 반환하는 Issue 후보 목록."""

    candidates: list[IssueCandidate] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def reject_duplicate_issue_ids(self) -> "IssueRetrievalResponse":
        """중복 후보를 막고 retrieval 점수 내림차순 계약을 검사한다."""

        issue_ids = [candidate.issue_id for candidate in self.candidates]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("Issue candidates must have unique issue IDs.")
        scores = [candidate.retrieval_score for candidate in self.candidates]
        if scores != sorted(scores, reverse=True):
            raise ValueError("Issue candidates must be ordered by retrieval score.")
        return self


class CandidateComparison(ContractModel):
    """하나의 Issue 후보와 입력 Bug를 비교한 구조화 결과."""

    issue_id: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_reasons: list[NonEmptyText] = Field(default_factory=list)
    contradictions: list[NonEmptyText] = Field(default_factory=list)
    missing_information: list[NonEmptyText] = Field(default_factory=list)


class MatchComparisonDraft(ContractModel):
    """LLM이 반환하는 후보별 비교 결과 묶음."""

    comparisons: list[CandidateComparison] = Field(min_length=1, max_length=5)


class MatchAction(StrEnum):
    """오케스트레이터가 RM 결과에 따라 수행할 다음 행동."""

    AUTO_LINK = "AUTO_LINK"
    REVIEW = "REVIEW"
    CREATE_NEW = "CREATE_NEW"


class MatchDecision(ContractModel):
    """정책 코드가 만든 RM의 최종 제안."""

    bug_id: int = Field(gt=0)
    action: MatchAction
    matched_issue_id: int | None = Field(default=None, gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_reasons: list[NonEmptyText] = Field(default_factory=list)
    contradictions: list[NonEmptyText] = Field(default_factory=list)
    review_reasons: list[NonEmptyText] = Field(default_factory=list)
    candidate_comparisons: list[CandidateComparison] = Field(
        default_factory=list,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_matched_issue(self) -> "MatchDecision":
        """신규 Issue 제안에는 기존 Issue ID가 섞이지 않게 한다."""

        if self.action is MatchAction.CREATE_NEW and self.matched_issue_id is not None:
            raise ValueError("CREATE_NEW must not contain matched_issue_id.")
        if self.action is not MatchAction.CREATE_NEW and self.matched_issue_id is None:
            raise ValueError("AUTO_LINK and REVIEW must contain matched_issue_id.")
        return self


class MatchPolicySettings(ContractModel):
    """운영 데이터에 맞춰 조정할 수 있는 RM 분기 임계치."""

    auto_link_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    review_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    candidate_margin: float = Field(default=0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_ordered_thresholds(self) -> "MatchPolicySettings":
        """검토 임계치가 자동 연결 임계치보다 높아지는 설정을 거부한다."""

        if self.review_threshold > self.auto_link_threshold:
            raise ValueError("review_threshold must not exceed auto_link_threshold.")
        return self
