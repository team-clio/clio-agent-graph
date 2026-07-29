"""Initial·Revision Judgment Subagent의 프롬프트."""

import json

from clio_agent_graph.analysis.models import CodeRelation, Evidence, JudgmentContext

COMMON_RULES = """공통 규칙:
1. 제공된 Issue, Bug, Evidence만 사용하세요.
2. Evidence에 없는 파일·심볼·코드 동작을 만들지 마세요.
3. Finding은 코드에서 직접 확인되는 사실만 표현하세요.
4. Hypothesis는 추론임을 유지하고 Finding을 통해서만 근거를 참조하세요.
5. 수정 방법, 테스트 계획, 우선순위, 심각도를 만들지 마세요.
6. 기술 식별자는 원문을 보존하고 설명은 입력 언어를 유지하세요.
"""

INITIAL_SYSTEM_PROMPT = (
    "당신은 새 Issue의 가능한 발생 원인을 조사하는 Initial Judgment Subagent입니다.\n"
    + COMMON_RULES
)

REVISION_SYSTEM_PROMPT = (
    "당신은 새 Bug를 반영해 기존 Issue 분석을 다시 판단하는 Revision Judgment Subagent입니다.\n"
    "이전 가설을 무조건 계승하지 말고 현재 코드에서 재확인된 Evidence만 새 판단에 사용하세요.\n"
    + COMMON_RULES
)


def build_plan_prompt(
    context: JudgmentContext,
    evidence: list[Evidence],
    asked_questions: list[str],
    *,
    correction_feedback: str | None = None,
) -> str:
    """다음 탐색 질문 생성에 필요한 문맥을 결정적인 JSON으로 만든다."""

    payload = {
        "context": context.model_dump(mode="json"),
        "current_evidence": [item.model_dump(mode="json") for item in evidence],
        "asked_questions": asked_questions,
    }
    return _build_prompt(
        "코드에서 아직 확인해야 할 질문을 최대 5개 만드세요. 충분하면 빈 목록을 반환하세요.",
        payload,
        correction_feedback,
    )


def build_analysis_prompt(
    context: JudgmentContext,
    evidence: list[Evidence],
    relations: list[CodeRelation],
    *,
    correction_feedback: str | None = None,
) -> str:
    """Finding·Hypothesis 초안 생성에 필요한 근거를 JSON으로 만든다."""

    payload = {
        "context": context.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "relations": [item.model_dump(mode="json") for item in relations],
    }
    return _build_prompt(
        "Evidence에서 직접 확인되는 Finding과 가능한 root cause Hypothesis를 만드세요.",
        payload,
        correction_feedback,
    )


def _build_prompt(
    instruction: str,
    payload: dict[str, object],
    correction_feedback: str | None,
) -> str:
    """모델 입력과 선택적인 교정 피드백을 하나의 문자열로 조립한다."""

    sections = [
        instruction,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    ]
    if correction_feedback is not None:
        sections.extend(("이전 응답의 검증 오류를 수정하세요:", correction_feedback))
    return "\n".join(sections)
