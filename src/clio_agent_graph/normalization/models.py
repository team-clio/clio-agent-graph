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
# Annotated는 str 타입에 "공백을 제거하고 빈 문자열은 거부한다"는 Pydantic 검증 규칙을 덧붙인다.


class ContractModel(BaseModel):
    """오타 난 필드가 조용히 통과하지 않도록 하는 NM 계약의 공통 설정."""

    # extra="forbid"는 모델에 정의하지 않은 필드가 들어오면 즉시 검증 오류를 낸다.
    model_config = ConfigDict(extra="forbid")


class MissingField(StrEnum):
    """원본 BugReport에서 확인할 수 없는 중요 정보."""

    # StrEnum은 enum 값이 JSON으로 변환될 때 일반 문자열처럼 표현된다.
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
    # `타입 | None`은 값이 해당 타입이거나 없을 수 있다는 Python 3.10+ 표기다.
    title: NonEmptyText | None = None
    description: NonEmptyText | None = None
    source: NonEmptyText | None = None
    error_type: NonEmptyText | None = None
    message: NonEmptyText | None = None
    # default_factory는 인스턴스마다 새로운 list/dict를 만들어 가변 객체 공유를 막는다.
    stack_trace: list[NonEmptyText] = Field(default_factory=list)
    occurred_at: datetime | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    # 이 decorator는 각 필드 검증이 끝난 뒤 모델 전체를 한 번 더 검사하게 한다.
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

    # field_validator는 지정한 필드 하나에 추가 검증 규칙을 적용한다.
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
