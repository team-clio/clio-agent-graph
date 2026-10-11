from clio_agent_graph.workflows.reporting.matching.models import (
    IssueCandidate,
    RepresentativeBug,
)
from clio_agent_graph.workflows.reporting.matching.prompts import build_user_prompt
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport


def _candidate() -> IssueCandidate:
    return IssueCandidate(
        issue_id=2,
        title="분봉 차트가 mock 데이터를 보여준다",
        retrieval_score=0.9,
        representative_bugs=[
            RepresentativeBug(
                bug_id=2,
                normalized_report=NormalizedReport(
                    bug_id=2,
                    observed_behavior="분봉 차트에 mock 캔들이 표시된다.",
                ),
            )
        ],
    )


def test_input_bug_is_labelled_and_placed_before_candidate_representative_bugs() -> None:
    report = NormalizedReport(bug_id=3, observed_behavior="placeholder 캔들의 거래량이 0이다.")

    prompt = build_user_prompt(report, [_candidate()])

    input_section = prompt.index("[input_bug]")
    candidate_section = prompt.index("[issue_candidates]")
    assert input_section < prompt.index("placeholder 캔들의 거래량이 0이다.") < candidate_section
    assert candidate_section < prompt.index("분봉 차트에 mock 캔들이 표시된다.")
    assert "representative_bugs는 기존 Issue의 대표 사례이며 입력 Bug가 아닙니다" in prompt


def test_prompt_is_identical_for_identical_input() -> None:
    report = NormalizedReport(bug_id=3, observed_behavior="placeholder 캔들의 거래량이 0이다.")

    assert build_user_prompt(report, [_candidate()]) == build_user_prompt(report, [_candidate()])


def test_correction_feedback_follows_comparison_material() -> None:
    report = NormalizedReport(bug_id=3, observed_behavior="placeholder 캔들의 거래량이 0이다.")

    prompt = build_user_prompt(report, [_candidate()], correction_feedback="issue_id 2 누락")

    assert prompt.endswith("이전 응답의 검증 오류를 수정하세요:\nissue_id 2 누락")
    assert prompt.index("[issue_candidates]") < prompt.index("issue_id 2 누락")
