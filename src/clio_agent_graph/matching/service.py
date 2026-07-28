"""후보 비교 결과를 검증하고 최종 MatchDecision을 만드는 서비스."""

import os

from pydantic import ValidationError

from clio_agent_graph.matching.errors import IssueMatchError, IssueMatchOutputError
from clio_agent_graph.matching.models import (
    CandidateComparison,
    IssueCandidate,
    MatchAction,
    MatchComparisonDraft,
    MatchDecision,
    MatchPolicySettings,
)
from clio_agent_graph.matching.ports import IssueMatchModel
from clio_agent_graph.normalization.models import NormalizedReport


class ReportMatcher:
    """후보 비교 모델과 명시적인 정책을 조합해 RM 결과를 만든다."""

    def __init__(
        self,
        model: IssueMatchModel,
        *,
        settings: MatchPolicySettings | None = None,
    ) -> None:
        self._model = model
        self._settings = settings if settings is not None else MatchPolicySettings()

    def match(
        self,
        *,
        bug_id: int,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
    ) -> MatchDecision:
        """후보가 없으면 즉시 신규 제안을, 있으면 비교 뒤 정책 결과를 반환한다."""

        comparisons = self.compare(report=report, candidates=candidates)
        return self.decide(
            bug_id=bug_id,
            report=report,
            candidates=candidates,
            comparisons=comparisons,
        )

    def compare(
        self,
        *,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
    ) -> list[CandidateComparison]:
        """후보를 비교하며, 후보가 없으면 모델 호출 없이 빈 목록을 반환한다."""

        if not candidates:
            return []
        return self._compare_with_one_retry(report, candidates)

    def decide(
        self,
        *,
        bug_id: int,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        comparisons: list[CandidateComparison],
    ) -> MatchDecision:
        """검증된 후보 비교를 최종 MatchDecision으로 바꾼다."""

        if not candidates:
            if comparisons:
                raise ValueError("Comparisons must be empty when there are no candidates.")
            return MatchDecision(
                bug_id=bug_id,
                action=MatchAction.CREATE_NEW,
                confidence=0.0,
                supporting_reasons=["유사한 기존 Issue 후보가 없습니다."],
            )

        draft = MatchComparisonDraft(comparisons=comparisons)
        self._validate_candidate_ids(draft, candidates)
        return self._apply_policy(
            bug_id=bug_id,
            report=report,
            candidates=candidates,
            comparisons=draft.comparisons,
        )

    def _compare_with_one_retry(
        self,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
    ) -> list[CandidateComparison]:
        """일시 실패 또는 잘못된 출력에 한 번의 재시도 기회를 준다."""

        correction_feedback: str | None = None
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                draft = self._model.compare(
                    report,
                    candidates,
                    correction_feedback=correction_feedback,
                )
                validated = MatchComparisonDraft.model_validate(draft)
                self._validate_candidate_ids(validated, candidates)
                return validated.comparisons
            except (IssueMatchOutputError, ValidationError) as error:
                last_error = error
                correction_feedback = str(error)[:2_000]
            except Exception as error:
                # provider의 일시 실패는 schema 교정 문구 없이 같은 요청으로 다시 시도한다.
                last_error = error
                correction_feedback = None

        if isinstance(last_error, (IssueMatchOutputError, ValidationError)):
            raise IssueMatchOutputError(
                "Issue match output remained invalid after one correction."
            ) from last_error
        raise IssueMatchError("Issue match model failed after one retry.") from last_error

    @staticmethod
    def _validate_candidate_ids(
        draft: MatchComparisonDraft,
        candidates: list[IssueCandidate],
    ) -> None:
        """모델이 모든 후보만 정확히 한 번씩 비교했는지 검사한다."""

        expected_ids = {candidate.issue_id for candidate in candidates}
        actual_ids = [comparison.issue_id for comparison in draft.comparisons]
        if len(actual_ids) != len(set(actual_ids)):
            raise IssueMatchOutputError("Candidate comparisons contain duplicate IDs.")
        if set(actual_ids) != expected_ids:
            raise IssueMatchOutputError(
                "Candidate comparison IDs do not match the retrieved candidates."
            )

    def _apply_policy(
        self,
        *,
        bug_id: int,
        report: NormalizedReport,
        candidates: list[IssueCandidate],
        comparisons: list[CandidateComparison],
    ) -> MatchDecision:
        """LLM의 비교 초안을 보수적인 애플리케이션 정책으로 분기한다."""

        ordered = sorted(comparisons, key=lambda item: item.confidence, reverse=True)
        top = ordered[0]
        candidate_by_id = {candidate.issue_id: candidate for candidate in candidates}
        top_candidate = candidate_by_id[top.issue_id]
        blockers = _auto_link_blockers(
            report=report,
            candidate=top_candidate,
            ordered_comparisons=ordered,
            settings=self._settings,
        )

        if top.confidence >= self._settings.auto_link_threshold and not blockers:
            action = MatchAction.AUTO_LINK
        elif top.confidence >= self._settings.review_threshold:
            action = MatchAction.REVIEW
        else:
            action = MatchAction.CREATE_NEW

        matched_issue_id = None if action is MatchAction.CREATE_NEW else top.issue_id
        return MatchDecision(
            bug_id=bug_id,
            action=action,
            matched_issue_id=matched_issue_id,
            confidence=top.confidence,
            supporting_reasons=top.supporting_reasons,
            contradictions=top.contradictions,
            review_reasons=[*top.missing_information, *blockers],
            candidate_comparisons=ordered,
        )


def load_match_policy_settings() -> MatchPolicySettings:
    """환경변수가 없으면 계획에서 확정한 보수적 기본값을 사용한다."""

    return MatchPolicySettings(
        auto_link_threshold=float(os.getenv("CLIO_RM_AUTO_LINK_THRESHOLD", "0.95")),
        review_threshold=float(os.getenv("CLIO_RM_REVIEW_THRESHOLD", "0.70")),
        candidate_margin=float(os.getenv("CLIO_RM_CANDIDATE_MARGIN", "0.10")),
    )


def _auto_link_blockers(
    *,
    report: NormalizedReport,
    candidate: IssueCandidate,
    ordered_comparisons: list[CandidateComparison],
    settings: MatchPolicySettings,
) -> list[str]:
    """AUTO_LINK를 막는 조건을 사람이 이해할 수 있는 이유로 반환한다."""

    blockers: list[str] = []
    top = ordered_comparisons[0]
    if report.observed_behavior is None:
        blockers.append("입력 Bug의 관찰된 현상이 없습니다.")
    if not any(report.affected_surface.model_dump().values()):
        blockers.append("입력 Bug의 영향 영역이 없습니다.")
    if not _has_strong_error_signal(report, candidate):
        blockers.append("정확히 일치하는 강한 오류 신호가 없습니다.")
    if top.contradictions:
        blockers.append("후보와 모순되는 중요 정보가 있습니다.")
    if len(ordered_comparisons) > 1:
        margin = top.confidence - ordered_comparisons[1].confidence
        if margin <= settings.candidate_margin:
            blockers.append("상위 두 후보의 신뢰도 차이가 충분하지 않습니다.")
    return blockers


def _has_strong_error_signal(
    report: NormalizedReport,
    candidate: IssueCandidate,
) -> bool:
    """같은 오류 유형과 코드 또는 stack frame이 대표 Bug에 있는지 확인한다."""

    input_signals = report.error_signals
    if input_signals.error_type is None:
        return False

    input_codes = set(input_signals.error_codes)
    input_frames = set(input_signals.stack_frames)
    for representative in candidate.representative_bugs:
        candidate_signals = representative.normalized_report.error_signals
        if candidate_signals.error_type != input_signals.error_type:
            continue
        if input_codes.intersection(candidate_signals.error_codes):
            return True
        if input_frames.intersection(candidate_signals.stack_frames):
            return True
    return False
