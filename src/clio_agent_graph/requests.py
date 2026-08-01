"""Root Graph가 수신하는 요청 계약."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ProcessReportPayload(BaseModel):
    """버그 리포트 처리에 필요한 입력."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1)


class AnalyzeIssuePayload(BaseModel):
    """이슈 분석에 필요한 입력."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)


class DocumentSyncPayload(BaseModel):
    """문서 등록·삭제 이벤트의 입력."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class RepositorySyncPayload(BaseModel):
    """레포지토리 등록·제거 이벤트의 입력."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    commit: str | None = None


class CodeChangePayload(BaseModel):
    """프로덕션 브랜치의 증분 변경 이벤트 입력."""

    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    before_commit: str = Field(min_length=1)
    after_commit: str = Field(min_length=1)


class ProcessReportRequest(BaseModel):
    """리포트 매칭부터 필요 시 신규 이슈 분석까지 실행하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["process_report"]
    project_id: str = Field(min_length=1)
    payload: ProcessReportPayload


class AnalyzeIssueRequest(BaseModel):
    """기존 이슈를 직접 분석하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["analyze_issue"]
    project_id: str = Field(min_length=1)
    payload: AnalyzeIssuePayload


class DocumentSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["document_added", "document_deleted"]
    project_id: str = Field(min_length=1)
    payload: DocumentSyncPayload


class RepositorySyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["repository_added", "repository_removed"]
    project_id: str = Field(min_length=1)
    payload: RepositorySyncPayload


class CodeChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    request_type: Literal["repository_changed"]
    project_id: str = Field(min_length=1)
    payload: CodeChangePayload


GraphRequest = Annotated[
    ProcessReportRequest
    | AnalyzeIssueRequest
    | DocumentSyncRequest
    | RepositorySyncRequest
    | CodeChangeRequest,
    Field(discriminator="request_type"),
]
graph_request_adapter: TypeAdapter[GraphRequest] = TypeAdapter(GraphRequest)
