"""Report Normalizer가 소유하는 최소 입출력 계약."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ContractModel(BaseModel):
    """오타 난 필드가 조용히 통과하지 않도록 하는 NM 계약의 공통 설정."""

    model_config = ConfigDict(extra="forbid")


class MissingField(StrEnum):
    """원본 BugReport에서 확인할 수 없는 중요 정보."""

    OBSERVED_BEHAVIOR = "OBSERVED_BEHAVIOR"
    EXPECTED_BEHAVIOR = "EXPECTED_BEHAVIOR"
    REPRODUCTION_CONDITIONS = "REPRODUCTION_CONDITIONS"
    REPRODUCTION_STEPS = "REPRODUCTION_STEPS"
    ENVIRONMENT = "ENVIRONMENT"
    AFFECTED_SURFACE = "AFFECTED_SURFACE"
    ERROR_TYPE = "ERROR_TYPE"
    ERROR_MESSAGE = "ERROR_MESSAGE"
    ERROR_CODE = "ERROR_CODE"
    STACK_TRACE = "STACK_TRACE"


class NormalizeReportInput(ContractModel):
    """Clio Server가 NM에 전달하는 원본 BugReport."""

    bug_report_id: int = Field(gt=0)
    title: NonEmptyText | None = None
    description: NonEmptyText | None = None
    source: NonEmptyText | None = None
    error_type: NonEmptyText | None = None
    message: NonEmptyText | None = None
    stack_trace: list[NonEmptyText] = Field(default_factory=list)
    occurred_at: datetime | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_report_content(self) -> "NormalizeReportInput":
        """식별자와 source만 있는 빈 리포트는 모델 호출 전에 거부한다."""

        content = (
            self.title,
            self.description,
            self.error_type,
            self.message,
            self.stack_trace,
            self.raw_payload,
        )
        if not any(content):
            raise ValueError("BugReport must contain at least one report content field.")
        return self


class Reproduction(ContractModel):
    """버그를 다시 발생시키는 사전 조건과 실행 순서."""

    conditions: list[NonEmptyText] = Field(default_factory=list)
    steps: list[NonEmptyText] = Field(default_factory=list)


class Environment(ContractModel):
    """버그가 발생한 실행 환경."""

    os: NonEmptyText | None = None
    os_version: NonEmptyText | None = None
    browser: NonEmptyText | None = None
    browser_version: NonEmptyText | None = None
    device: NonEmptyText | None = None
    app_version: NonEmptyText | None = None
    deployment: NonEmptyText | None = None
    additional: dict[NonEmptyText, NonEmptyText] = Field(default_factory=dict)


class AffectedSurface(ContractModel):
    """문제가 관찰된 사용자 기능 또는 기술 표면."""

    feature: NonEmptyText | None = None
    operation: NonEmptyText | None = None
    endpoint: NonEmptyText | None = None
    screen: NonEmptyText | None = None


class ErrorSignals(ContractModel):
    """RM이 정확·유사 매칭에 사용할 수 있는 오류 식별 신호."""

    error_type: NonEmptyText | None = None
    message: NonEmptyText | None = None
    error_codes: list[NonEmptyText] = Field(default_factory=list)
    stack_frames: list[NonEmptyText] = Field(default_factory=list)


class NormalizedReport(ContractModel):
    """소스 형식과 무관하게 RM이 소비하는 표준 BugReport 표현."""

    bug_report_id: int = Field(gt=0)
    observed_behavior: NonEmptyText | None = None
    expected_behavior: NonEmptyText | None = None
    reproduction: Reproduction = Field(default_factory=Reproduction)
    environment: Environment = Field(default_factory=Environment)
    affected_surface: AffectedSurface = Field(default_factory=AffectedSurface)
    error_signals: ErrorSignals = Field(default_factory=ErrorSignals)
    missing_fields: list[MissingField] = Field(default_factory=list)

    @field_validator("missing_fields")
    @classmethod
    def reject_duplicate_missing_fields(
        cls,
        value: list[MissingField],
    ) -> list[MissingField]:
        """동일 누락 항목이 반복되어 후속 정책 점수에 중복 반영되는 것을 막는다."""

        if len(value) != len(set(value)):
            raise ValueError("missing_fields must not contain duplicates.")
        return value
