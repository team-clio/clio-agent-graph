"""Root Graph가 수신하는 요청 계약."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

MAX_LONG_ID = 9_223_372_036_854_775_807


def _validate_long_id(value: str) -> str:
    if int(value) > MAX_LONG_ID:
        raise ValueError("ID exceeds the signed 64-bit range")
    return value


class ProcessReportPayload(BaseModel):
    """버그 리포트 처리에 필요한 입력."""

    model_config = ConfigDict(extra="forbid")

    bug_id: str = Field(pattern=r"^[1-9]\d*$")

    _validate_bug_id = field_validator("bug_id")(_validate_long_id)


class AnalyzeIssuePayload(BaseModel):
    """이슈 분석에 필요한 입력."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(pattern=r"^[1-9]\d*$")

    _validate_issue_id = field_validator("issue_id")(_validate_long_id)


class CodeEvidenceCitationPayload(BaseModel):
    """IDE 코드 뷰가 표시할 검증된 코드 근거 위치."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    file_path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    observation: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "CodeEvidenceCitationPayload":
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class ReadCodeEvidencePayload(BaseModel):
    """고정 commit의 citation 주변 코드 발췌를 읽는 입력."""

    model_config = ConfigDict(extra="forbid")

    citations: list[CodeEvidenceCitationPayload] = Field(min_length=1, max_length=50)


class ReadCodeEvidenceRequest(BaseModel):
    """분석 snapshot에 저장된 코드 근거를 읽기 전용으로 조회한다."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["read_code_evidence"]
    project_id: str = Field(pattern=r"^[1-9]\d*$")
    payload: ReadCodeEvidencePayload

    _validate_project_id = field_validator("project_id")(_validate_long_id)


class DocumentUpsertPayload(BaseModel):
    """정규화 Markdown 문서를 PCM에 등록하는 입력."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    source_metadata: dict[str, object] = Field(default_factory=dict)


class DocumentDeletePayload(BaseModel):
    """PCM에서 원본 문서 revision을 제거하는 입력."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class RepositorySyncPayload(BaseModel):
    """레포지토리 등록·제거 이벤트의 입력."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    source_uri: str | None = Field(default=None, min_length=1)
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class CodeChangePayload(BaseModel):
    """프로덕션 브랜치의 증분 변경 이벤트 입력."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    before_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    after_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


class ProcessReportRequest(BaseModel):
    """리포트 매칭부터 필요 시 신규 이슈 분석까지 실행하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["process_report"]
    project_id: str = Field(pattern=r"^[1-9]\d*$")
    payload: ProcessReportPayload

    _validate_project_id = field_validator("project_id")(_validate_long_id)


class AnalyzeIssueRequest(BaseModel):
    """기존 이슈를 직접 분석하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["analyze_issue"]
    project_id: str = Field(pattern=r"^[1-9]\d*$")
    payload: AnalyzeIssuePayload

    _validate_project_id = field_validator("project_id")(_validate_long_id)


class DocumentAddedRequest(BaseModel):
    """새 문서 revision을 PCM Knowledge로 반영하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["document_added"]
    project_id: str = Field(min_length=1)
    payload: DocumentUpsertPayload


class DocumentDeletedRequest(BaseModel):
    """문서 revision 삭제를 PCM과 검색 인덱스에 반영하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["document_deleted"]
    project_id: str = Field(min_length=1)
    payload: DocumentDeletePayload


class RepositorySyncRequest(BaseModel):
    """Repository 등록과 제거가 공유하는 lifecycle 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["repository_added", "repository_removed"]
    project_id: str = Field(min_length=1)
    payload: RepositorySyncPayload

    @model_validator(mode="after")
    def require_source_for_registration(self) -> "RepositorySyncRequest":
        """등록 요청에만 필요한 원격 주소를 판별 공용체 검증 단계에서 강제한다."""

        if self.request_type == "repository_added" and not self.payload.source_uri:
            raise ValueError("repository_added requires payload.source_uri")
        return self


class CodeChangeRequest(BaseModel):
    """활성 Repository revision을 새 commit으로 전진시키는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["repository_changed"]
    project_id: str = Field(min_length=1)
    payload: CodeChangePayload


GraphRequest = Annotated[
    ProcessReportRequest
    | AnalyzeIssueRequest
    | ReadCodeEvidenceRequest
    | DocumentAddedRequest
    | DocumentDeletedRequest
    | RepositorySyncRequest
    | CodeChangeRequest,
    Field(discriminator="request_type"),
]
graph_request_adapter: TypeAdapter[GraphRequest] = TypeAdapter(GraphRequest)
