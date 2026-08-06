"""NormalizedReport를 exact·문자열·vector 채널이 공유하는 질의로 투영한다."""

import hashlib
import json

from clio_agent_graph.matching.models import IssueRetrievalRequest
from clio_agent_graph.normalization.models import NormalizedReport
from clio_agent_graph.retrieval.models import BugSearchQuery


def build_search_text(report: NormalizedReport) -> str:
    """NM에 실제로 존재하는 값만 고정된 순서로 검색 문서에 넣는다."""

    rows: list[str] = []
    _append(rows, "observed_behavior", report.observed_behavior)
    _append(rows, "expected_behavior", report.expected_behavior)
    _extend(rows, "reproduction_condition", report.reproduction.conditions)
    _extend(rows, "reproduction_step", report.reproduction.steps)
    for name, value in report.environment.model_dump(exclude_none=True).items():
        if name == "additional":
            for key, item in sorted(value.items()):
                _append(rows, f"environment.{key}", item)
        else:
            _append(rows, f"environment.{name}", value)
    for name, value in report.affected_surface.model_dump(exclude_none=True).items():
        _append(rows, f"affected_surface.{name}", value)
    _append(rows, "error_type", report.error_signals.error_type)
    _append(rows, "error_message", report.error_signals.message)
    _extend(rows, "error_code", report.error_signals.error_codes)
    _extend(rows, "stack_frame", report.error_signals.stack_frames)
    # bug_report_id만 있는 빈 문서는 NM 계약상 가능하므로 식별 가능한 안전한 문구를 사용한다.
    return "\n".join(rows) or "reported bug"


def build_search_query(request: IssueRetrievalRequest) -> BugSearchQuery:
    """RM 요청을 검색 채널 공통 계약으로 바꾼다."""

    signals = request.normalized_report.error_signals
    return BugSearchQuery(
        project_id=request.project_id,
        bug_id=request.bug_id,
        search_text=build_search_text(request.normalized_report),
        error_type=_normalize_signal(signals.error_type),
        error_codes=_unique_normalized(signals.error_codes),
        stack_frames=_unique_normalized(signals.stack_frames),
    )


def calculate_document_hash(report: NormalizedReport, search_text: str) -> str:
    """같은 정규화 snapshot의 재색인을 멱등하게 식별한다."""

    payload = {
        "normalized_report": report.model_dump(mode="json"),
        "search_text": search_text,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _append(rows: list[str], label: str, value: object | None) -> None:
    """값이 있을 때만 사람이 읽을 수 있는 label 행을 추가한다."""

    if value is not None and str(value).strip():
        rows.append(f"{label}: {str(value).strip()}")


def _extend(rows: list[str], label: str, values: list[str]) -> None:
    """목록의 순서를 보존하며 각 값을 별도 행으로 추가한다."""

    for value in values:
        _append(rows, label, value)


def _normalize_signal(value: str | None) -> str | None:
    """exact 검색 비교를 위해 대소문자와 연속 공백 차이를 제거한다."""

    if value is None:
        return None
    normalized = " ".join(value.casefold().split())
    return normalized or None


def _unique_normalized(values: list[str]) -> list[str]:
    """원래 순서를 유지하면서 같은 exact signal의 반복을 제거한다."""

    result: list[str] = []
    for value in values:
        normalized = _normalize_signal(value)
        if normalized is not None and normalized not in result:
            result.append(normalized)
    return result
