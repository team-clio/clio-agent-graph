from collections.abc import Sequence
from copy import deepcopy

import pytest

from clio_agent_graph.workflows.reporting.normalization import (
    AffectedSurface,
    Environment,
    ErrorSignals,
    MissingField,
    NormalizationDraft,
    NormalizeReportInput,
    Reproduction,
)
from clio_agent_graph.workflows.reporting.normalization.ports import NormalizationOutputError
from clio_agent_graph.workflows.reporting.normalization.service import (
    REDACTED_VALUE,
    ReportNormalizer,
    ReportPayloadTooLargeError,
)


class FakeNormalizationModel:
    """호출 순서대로 준비된 결과 또는 오류를 반환하는 테스트 모델."""

    def __init__(self, responses: Sequence[NormalizationDraft | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[str, str | None]] = []

    def extract(
        self,
        report_text: str,
        *,
        correction_feedback: str | None = None,
    ) -> NormalizationDraft:
        self.calls.append((report_text, correction_feedback))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_structured_error_signals_take_precedence_over_model_draft() -> None:
    model = FakeNormalizationModel(
        [
            NormalizationDraft(
                observed_behavior="결제 요청이 실패한다.",
                error_signals=ErrorSignals(
                    error_type="ModelException",
                    message="model message",
                    stack_frames=["Model.call"],
                ),
            )
        ]
    )
    report = NormalizeReportInput(
        bug_report_id=351,
        description="결제 요청이 실패합니다.",
        error_type="NullPointerException",
        message="payment must not be null",
        stack_trace=["PaymentService.pay"],
    )

    result = ReportNormalizer(model).normalize(report)

    assert result.bug_report_id == 351
    assert result.error_signals.error_type == "NullPointerException"
    assert result.error_signals.message == "payment must not be null"
    assert result.error_signals.stack_frames == ["PaymentService.pay"]


def test_missing_fields_are_calculated_from_the_merged_result() -> None:
    model = FakeNormalizationModel(
        [
            NormalizationDraft(
                observed_behavior="결제 요청이 실패한다.",
                reproduction=Reproduction(steps=["결제 버튼 클릭"]),
                environment=Environment(os="iOS"),
                affected_surface=AffectedSurface(feature="결제"),
                error_signals=ErrorSignals(error_codes=["500"]),
            )
        ]
    )
    report = NormalizeReportInput(
        bug_report_id=351,
        description="결제 버튼을 클릭하면 실패합니다.",
        message="Internal Server Error",
    )

    result = ReportNormalizer(model).normalize(report)

    assert result.expected_behavior is None
    assert result.missing_fields == [
        MissingField.EXPECTED_BEHAVIOR,
        MissingField.REPRODUCTION_CONDITIONS,
        MissingField.ERROR_TYPE,
        MissingField.STACK_TRACE,
    ]


def test_invalid_output_is_corrected_only_once() -> None:
    model = FakeNormalizationModel(
        [
            NormalizationOutputError("observed_behavior is invalid"),
            NormalizationDraft(observed_behavior="로그인에 실패한다."),
        ]
    )
    report = NormalizeReportInput(bug_report_id=1, description="로그인에 실패합니다.")

    result = ReportNormalizer(model).normalize(report)

    assert result.observed_behavior == "로그인에 실패한다."
    assert len(model.calls) == 2
    assert model.calls[0][1] is None
    assert "observed_behavior is invalid" in (model.calls[1][1] or "")


def test_second_invalid_output_fails_without_partial_result() -> None:
    model = FakeNormalizationModel(
        [
            NormalizationOutputError("first invalid output"),
            NormalizationOutputError("second invalid output"),
        ]
    )
    report = NormalizeReportInput(bug_report_id=1, description="로그인에 실패합니다.")

    with pytest.raises(NormalizationOutputError, match="after one correction"):
        ReportNormalizer(model).normalize(report)

    assert len(model.calls) == 2


def test_provider_error_is_not_treated_as_a_correctable_output_error() -> None:
    model = FakeNormalizationModel([RuntimeError("provider unavailable")])
    report = NormalizeReportInput(bug_report_id=1, description="로그인에 실패합니다.")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        ReportNormalizer(model).normalize(report)

    assert len(model.calls) == 1


def test_sensitive_raw_payload_values_are_redacted_without_mutating_input() -> None:
    raw_payload = {
        "user": {"password": "plain-text", "access_token": "secret-token"},
        "headers": {"Authorization": "Bearer abc", "Content-Type": "application/json"},
        "events": [{"cookie-value": "session=abc", "status": 500}],
    }
    original_payload = deepcopy(raw_payload)
    model = FakeNormalizationModel([NormalizationDraft(observed_behavior="요청이 실패한다.")])
    report = NormalizeReportInput(
        bug_report_id=1,
        description="요청이 실패합니다.",
        raw_payload=raw_payload,
    )

    ReportNormalizer(model).normalize(report)

    report_text = model.calls[0][0]
    assert REDACTED_VALUE in report_text
    assert "plain-text" not in report_text
    assert "secret-token" not in report_text
    assert "Bearer abc" not in report_text
    assert "session=abc" not in report_text
    assert "application/json" in report_text
    assert report.raw_payload == original_payload


def test_raw_payload_limit_accepts_boundary_and_rejects_one_byte_less() -> None:
    raw_payload = {"data": "가나다"}
    serialized_size = len('{"data":"가나다"}'.encode())
    report = NormalizeReportInput(
        bug_report_id=1,
        description="오류가 발생합니다.",
        raw_payload=raw_payload,
    )

    accepted_model = FakeNormalizationModel([NormalizationDraft()])
    ReportNormalizer(
        accepted_model,
        max_raw_payload_bytes=serialized_size,
    ).normalize(report)

    rejected_model = FakeNormalizationModel([NormalizationDraft()])
    with pytest.raises(ReportPayloadTooLargeError, match="exceeds the configured limit"):
        ReportNormalizer(
            rejected_model,
            max_raw_payload_bytes=serialized_size - 1,
        ).normalize(report)

    assert rejected_model.calls == []
