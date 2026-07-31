"""Issue Retrieval Agent 내부에서 사용하는 검증 가능한 데이터 계약."""

from enum import StrEnum

from pydantic import Field, model_validator

from clio_agent_graph.normalization.models import ContractModel, NonEmptyText, NormalizedReport


class SearchChannel(StrEnum):
    """하나의 Bug를 발견한 검색 방식."""

    EXACT = "EXACT"
    LEXICAL = "LEXICAL"
    VECTOR = "VECTOR"


class RetrievalSettings(ContractModel):
    """운영 평가 뒤 바꿀 수 있는 Retrieval 실행 상한과 점수 설정."""

    channel_limit: int = Field(default=50, ge=1, le=500)
    fused_bug_limit: int = Field(default=50, ge=1, le=500)
    hydrated_issue_limit: int = Field(default=20, ge=1, le=100)
    final_issue_limit: int = Field(default=5, ge=1, le=5)
    representative_bug_limit: int = Field(default=3, ge=1, le=3)
    rrf_constant: int = Field(default=60, ge=1)
    exact_weight: float = Field(default=2.0, gt=0)
    lexical_weight: float = Field(default=1.0, gt=0)
    vector_weight: float = Field(default=1.0, gt=0)
    second_hit_bonus: float = Field(default=0.10, ge=0.0, le=1.0)
    third_hit_bonus: float = Field(default=0.05, ge=0.0, le=1.0)
    lexical_threshold: float = Field(default=0.10, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_ordered_limits(self) -> "RetrievalSettings":
        """후속 단계의 후보 수가 앞 단계보다 커지는 잘못된 설정을 막는다."""

        if self.fused_bug_limit > self.channel_limit * 3:
            raise ValueError("fused_bug_limit exceeds the possible channel result pool.")
        if self.final_issue_limit > self.hydrated_issue_limit:
            raise ValueError("final_issue_limit must not exceed hydrated_issue_limit.")
        return self


class BugSearchQuery(ContractModel):
    """NormalizedReport에서 원문 사실만 투영한 검색 질의."""

    project_id: int = Field(gt=0)
    bug_id: int = Field(gt=0)
    search_text: NonEmptyText
    error_type: NonEmptyText | None = None
    error_codes: list[NonEmptyText] = Field(default_factory=list)
    stack_frames: list[NonEmptyText] = Field(default_factory=list)


class RetrievalScope(ContractModel):
    """현재 요청에서 검색 가능한 corpus와 제외 대상을 설명한다."""

    excluded_issue_ids: list[int] = Field(default_factory=list)
    eligible_bug_count: int = Field(ge=0)
    indexed_bug_count: int = Field(ge=0)

    @model_validator(mode="after")
    def reject_impossible_coverage(self) -> "RetrievalScope":
        """색인 수가 검색 대상 수보다 많은 모순된 집계를 막는다."""

        if self.indexed_bug_count > self.eligible_bug_count:
            raise ValueError("indexed_bug_count must not exceed eligible_bug_count.")
        return self


class BugSearchHit(ContractModel):
    """하나의 검색 채널이 반환한 기존 Bug 순위."""

    bug_id: int = Field(gt=0)
    channel: SearchChannel
    rank: int = Field(ge=1)
    raw_score: float = Field(ge=0.0, le=1.0)
    matched_signals: list[NonEmptyText] = Field(default_factory=list)
    exact_signal_count: int = Field(default=0, ge=0)


class FusedBugHit(ContractModel):
    """여러 채널의 순위를 weighted RRF로 합친 Bug."""

    bug_id: int = Field(gt=0)
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[NonEmptyText] = Field(default_factory=list)
    exact_signal_count: int = Field(default=0, ge=0)


class StoredRepresentativeBug(ContractModel):
    """DB snapshot에서 복원한 RM 비교용 대표 Bug."""

    bug_id: int = Field(gt=0)
    normalized_report: NormalizedReport
    occurrence_count: int = Field(default=1, gt=0)


class HydratedIssue(ContractModel):
    """검색된 Bug들과 연결된 Issue의 읽기 전용 projection."""

    issue_id: int = Field(gt=0)
    title: NonEmptyText | None = None
    summary: NonEmptyText | None = None
    status: NonEmptyText | None = None
    bugs: list[StoredRepresentativeBug] = Field(default_factory=list)


class IndexStatus(StrEnum):
    """단일 Bug indexing이 새 데이터를 만들었는지 나타낸다."""

    CREATED = "CREATED"
    UNCHANGED = "UNCHANGED"


class BugIndexInput(ContractModel):
    """Supervisor가 NM 결과를 비동기 색인 graph에 전달하는 입력."""

    project_id: int = Field(gt=0)
    bug_id: int = Field(gt=0)
    normalized_report: NormalizedReport


class BugIndexResult(ContractModel):
    """색인된 snapshot과 embedding을 추적하는 공개 결과."""

    project_id: int = Field(gt=0)
    bug_id: int = Field(gt=0)
    bug_report_id: int = Field(gt=0)
    document_id: int = Field(gt=0)
    document_version: int = Field(gt=0)
    document_hash: NonEmptyText
    embedding_model: NonEmptyText
    embedding_dimension: int = Field(gt=0)
    status: IndexStatus


class BackfillInput(ContractModel):
    """기존 Bug를 ID cursor 순서로 나눠 색인하는 요청."""

    project_id: int = Field(gt=0)
    after_bug_id: int | None = Field(default=None, ge=0)
    batch_size: int = Field(default=20, ge=1, le=100)


class BackfillFailure(ContractModel):
    """전체 기술 장애가 아닌 하나의 과거 Bug 데이터 문제."""

    bug_id: int = Field(gt=0)
    reason: NonEmptyText


class BackfillResult(ContractModel):
    """호출자가 다음 batch와 개별 보정 대상을 알 수 있는 결과."""

    project_id: int = Field(gt=0)
    processed_count: int = Field(ge=0)
    indexed_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    failures: list[BackfillFailure] = Field(default_factory=list, max_length=100)
    next_after_bug_id: int | None = Field(default=None, gt=0)
    has_more: bool
