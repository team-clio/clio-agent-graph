"""모델 추출 결과를 신뢰 가능한 NormalizedReport로 조립하는 서비스."""

import json
import re
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from clio_agent_graph.runtime.agent_runtime import ToolCallRecord
from clio_agent_graph.workflows.reporting.normalization.models import (
    AffectedSurface,
    Environment,
    ErrorSignals,
    MissingField,
    NormalizationDraft,
    NormalizedReport,
    NormalizeReportInput,
)
from clio_agent_graph.workflows.reporting.normalization.ports import (
    NormalizationModel,
    NormalizationOutputError,
)

DEFAULT_MAX_RAW_PAYLOAD_BYTES = 32 * 1024
REDACTED_VALUE = "[REDACTED]"

# 대소문자와 `_`, `-` 차이를 없앤 key에 아래 단어가 포함되면 값 전체를 가린다.
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "authorization",
    "cookie",
    "apikey",
    "credential",
)


class ReportPayloadTooLargeError(ValueError):
    """마스킹한 raw payload가 허용된 모델 입력 크기를 넘었을 때 발생하는 오류."""


class ReportNormalizer:
    """Bug를 모델로 구조화하고 애플리케이션 규칙으로 최종 결과를 만든다."""

    def __init__(
        self,
        model: NormalizationModel,
        *,
        max_raw_payload_bytes: int = DEFAULT_MAX_RAW_PAYLOAD_BYTES,
    ) -> None:
        if max_raw_payload_bytes <= 0:
            raise ValueError("max_raw_payload_bytes must be greater than zero.")
        self._model = model
        self._max_raw_payload_bytes = max_raw_payload_bytes

    def normalize(self, report: NormalizeReportInput) -> NormalizedReport:
        """리포트를 정규화하며 모델 출력 검증 실패는 한 번만 교정한다."""

        report_text = self._build_report_text(report)
        draft = self._extract_with_one_correction(report_text)
        return self._build_result(report, draft)

    @property
    def last_tool_calls(self) -> list[ToolCallRecord]:
        """모델 adapter가 지원하면 직전 자율 조사 Tool 기록을 반환한다."""

        calls = getattr(self._model, "last_tool_calls", [])
        return [dict(item) for item in calls]

    def _extract_with_one_correction(self, report_text: str) -> NormalizationDraft:
        """첫 structured output 오류를 피드백하고 두 번째 오류는 명시적으로 실패시킨다."""

        try:
            first_result = self._model.extract(report_text)
            return NormalizationDraft.model_validate(first_result)
        except (NormalizationOutputError, ValidationError) as first_error:
            feedback = _format_validation_feedback(first_error)

        try:
            corrected_result = self._model.extract(
                report_text,
                correction_feedback=feedback,
            )
            return NormalizationDraft.model_validate(corrected_result)
        except (NormalizationOutputError, ValidationError) as second_error:
            raise NormalizationOutputError(
                "Normalization output remained invalid after one correction."
            ) from second_error

    def _build_report_text(self, report: NormalizeReportInput) -> str:
        """구조화 필드와 보호 처리한 raw payload를 모델용 텍스트로 직렬화한다."""

        structured_fields = report.model_dump(
            mode="json",
            exclude={"bug_id", "raw_payload"},
        )
        raw_payload = _sanitize_raw_payload(report.raw_payload)
        raw_payload_json = _serialize_json(raw_payload)
        raw_payload_size = len(raw_payload_json.encode("utf-8"))
        if raw_payload_size > self._max_raw_payload_bytes:
            raise ReportPayloadTooLargeError(
                "raw_payload exceeds the configured limit: "
                f"{raw_payload_size} > {self._max_raw_payload_bytes} bytes."
            )

        return "\n".join(
            (
                "[STRUCTURED_FIELDS]",
                _serialize_json(structured_fields),
                "[RAW_PAYLOAD]",
                raw_payload_json,
            )
        )

    @staticmethod
    def _build_result(
        report: NormalizeReportInput,
        draft: NormalizationDraft,
    ) -> NormalizedReport:
        """명시적인 수집 필드를 우선해 초안과 병합하고 누락 정보를 계산한다."""

        error_signals = ErrorSignals(
            error_type=report.error_type or draft.error_signals.error_type,
            message=report.message or draft.error_signals.message,
            error_codes=draft.error_signals.error_codes,
            stack_frames=report.stack_trace or draft.error_signals.stack_frames,
        )
        missing_fields = _calculate_missing_fields(
            observed_behavior=draft.observed_behavior,
            expected_behavior=draft.expected_behavior,
            reproduction_conditions=draft.reproduction.conditions,
            reproduction_steps=draft.reproduction.steps,
            environment=draft.environment,
            affected_surface=draft.affected_surface,
            error_signals=error_signals,
        )
        return NormalizedReport(
            bug_id=report.bug_id,
            observed_behavior=draft.observed_behavior,
            expected_behavior=draft.expected_behavior,
            reproduction=draft.reproduction,
            environment=draft.environment,
            affected_surface=draft.affected_surface,
            error_signals=error_signals,
            missing_fields=missing_fields,
        )


def _sanitize_raw_payload(value: Any, *, parent_key: str | None = None) -> Any:
    """원본을 바꾸지 않고 중첩 dict/list의 민감 key 값을 재귀적으로 가린다."""

    if parent_key is not None and _is_sensitive_key(parent_key):
        return REDACTED_VALUE
    if isinstance(value, dict):
        return {
            str(key): _sanitize_raw_payload(item, parent_key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_raw_payload(item) for item in value]
    return deepcopy(value)


def _is_sensitive_key(key: str) -> bool:
    """key의 구분 문자와 대소문자를 무시하고 민감정보 key인지 확인한다."""

    normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
    return any(part in normalized_key for part in SENSITIVE_KEY_PARTS)


def _serialize_json(value: Any) -> str:
    """동일 입력이 항상 같은 모델 텍스트가 되도록 JSON key를 정렬한다."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _format_validation_feedback(error: Exception) -> str:
    """교정 프롬프트가 과도하게 커지지 않도록 검증 오류를 제한한다."""

    return str(error)[:2_000]


def _calculate_missing_fields(
    *,
    observed_behavior: str | None,
    expected_behavior: str | None,
    reproduction_conditions: list[str],
    reproduction_steps: list[str],
    environment: Environment,
    affected_surface: AffectedSurface,
    error_signals: ErrorSignals,
) -> list[MissingField]:
    """최종 결과에서 비어 있는 항목을 고정된 순서로 계산한다."""

    missing: list[MissingField] = []
    if observed_behavior is None:
        missing.append(MissingField.OBSERVED_BEHAVIOR)
    if expected_behavior is None:
        missing.append(MissingField.EXPECTED_BEHAVIOR)
    if not reproduction_conditions:
        missing.append(MissingField.REPRODUCTION_CONDITIONS)
    if not reproduction_steps:
        missing.append(MissingField.REPRODUCTION_STEPS)
    if not _has_environment_value(environment):
        missing.append(MissingField.ENVIRONMENT)
    if not any(affected_surface.model_dump().values()):
        missing.append(MissingField.AFFECTED_SURFACE)
    if error_signals.error_type is None:
        missing.append(MissingField.ERROR_TYPE)
    if error_signals.message is None:
        missing.append(MissingField.ERROR_MESSAGE)
    if not error_signals.error_codes:
        missing.append(MissingField.ERROR_CODE)
    if not error_signals.stack_frames:
        missing.append(MissingField.STACK_TRACE)
    return missing


def _has_environment_value(environment: Environment) -> bool:
    """고정 환경 필드나 프로젝트별 추가 환경값이 하나라도 있는지 확인한다."""

    return any(environment.model_dump().values())
