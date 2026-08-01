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


class ProcessReportRequest(BaseModel):
    """리포트 매칭부터 필요 시 신규 이슈 분석까지 실행하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    type: Literal["process_report"]
    project_id: str = Field(min_length=1)
    payload: ProcessReportPayload


class AnalyzeIssueRequest(BaseModel):
    """기존 이슈를 직접 분석하는 요청."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    type: Literal["analyze_issue"]
    project_id: str = Field(min_length=1)
    payload: AnalyzeIssuePayload


GraphRequest = Annotated[
    ProcessReportRequest | AnalyzeIssueRequest,
    Field(discriminator="type"),
]
graph_request_adapter: TypeAdapter[GraphRequest] = TypeAdapter(GraphRequest)
