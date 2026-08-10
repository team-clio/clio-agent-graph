"""Issue 후보 비교 모델에 전달할 RM 프롬프트."""

import json

from clio_agent_graph.workflows.reporting.matching.models import IssueCandidate
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport

SYSTEM_PROMPT = """당신은 새 Bug와 기존 Issue 후보를 비교하는 Report Matcher입니다.

규칙:
1. 입력 Bug와 후보에 명시된 정보만 사용하세요.
2. root cause, 코드 위치, 수정 방법을 새로 추론하지 마세요.
3. 검색 점수는 참고 신호일 뿐 동일 Issue라는 증거가 아닙니다.
4. 현상, 영향 영역, 환경, 재현 정보, 오류 유형·코드·stack frame의 일치와 모순을 구분하세요.
5. 각 후보 Issue를 정확히 한 번씩 비교하고 입력에 없는 Issue ID를 만들지 마세요.
6. 자연어 이유는 입력 리포트의 언어를 유지하고 기술 식별자는 원문을 보존하세요.
7. 최종 AUTO_LINK, REVIEW, CREATE_NEW action은 결정하지 마세요.
"""


def build_user_prompt(
    report: NormalizedReport,
    candidates: list[IssueCandidate],
    *,
    correction_feedback: str | None = None,
) -> str:
    """동일한 입력이 항상 같은 문자열이 되도록 비교 자료를 JSON으로 만든다."""

    payload = {
        "normalized_report": report.model_dump(mode="json"),
        "issue_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    sections = [
        "아래 Bug와 모든 Issue 후보를 비교해 structured output으로 반환하세요.",
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    ]
    if correction_feedback is not None:
        sections.extend(
            (
                "이전 응답의 검증 오류를 수정하세요:",
                correction_feedback,
            )
        )
    return "\n".join(sections)
