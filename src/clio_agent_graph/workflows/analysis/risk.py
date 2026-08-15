"""이슈 위험도(0-100) 평가와 P0~P4 우선순위 매핑.

위험도 점수는 LLM이 산출하고, 점수 대역 → P0~P4 매핑은 코드가 결정한다.
대역 경계는 clio-server의 ``RiskPriorityMapper``와 반드시 동일하게 유지한다.
"""

from pydantic import BaseModel, Field

# (min, max, priority, label, description)
RISK_BANDS: tuple[tuple[int, int, str, str, str], ...] = (
    (0, 29, "P4", "미미", "표시 오류·폴리싱 수준, 영향이 거의 없음"),
    (30, 49, "P3", "낮음", "사소한 오류, 드물게 발생, 우회 쉬움"),
    (50, 69, "P2", "보통", "일부 기능 장애, 우회 가능, 상당수 사용자 영향"),
    (70, 84, "P1", "높음", "핵심 기능 차단, 우회 불가, 다수 사용자 영향"),
    (85, 100, "P0", "긴급", "서비스 전면 중단, 데이터 손실·보안 사고, 즉시 대응"),
)


def map_risk_to_priority(risk_score: int) -> str:
    """0~100 위험도 점수를 P0~P4 우선순위로 변환한다."""

    if not isinstance(risk_score, int) or isinstance(risk_score, bool):
        raise ValueError(f"risk_score must be an integer between 0 and 100: {risk_score!r}")
    for low, high, priority, _label, _description in RISK_BANDS:
        if low <= risk_score <= high:
            return priority
    raise ValueError(f"risk_score must be between 0 and 100: {risk_score!r}")


class RiskFactor(BaseModel):
    """위험도 판단에 사용한 개별 요인의 점수와 근거."""

    name: str = Field(min_length=1, max_length=40)
    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1)


class RiskAssessment(BaseModel):
    """LLM이 산출한 이슈 위험도 평가 결과."""

    risk_score: int = Field(ge=0, le=100)
    factors: list[RiskFactor] = Field(min_length=1, max_length=6)
    rationale: str = Field(min_length=1)

    @property
    def priority(self) -> str:
        """risk_score에서 파생된 P0~P4 우선순위."""

        return map_risk_to_priority(self.risk_score)


RISK_RUBRIC = """You assess the business risk of a software issue on a 0-100 scale so it can be \
prioritized for engineering triage.

Score the following factors from 0 (negligible) to 100 (catastrophic):
- 영향 범위 (impact_scope): how many users, features, and flows are affected.
- 심각도 (severity): crash, data loss, security exposure, or data corruption.
- 발생 빈도·재현성 (frequency): how often it occurs and how reliably it reproduces.
- 우회 가능성 (workaround): how easily users can work around it (easier = lower score).
- 비즈니스 임계성 (business_criticality): payment, account, or core-path impact.

Calibrate the overall risk_score to this priority banding:
  0-29   = P4 미미  (cosmetic / negligible impact)
  30-49  = P3 낮음  (minor, rare, easy workaround)
  50-69  = P2 보통  (partial feature broken, workaround exists)
  70-84  = P1 높음  (core feature blocked, no workaround, many users)
  85-100 = P0 긴급  (full outage, data loss, or security incident)

Write rationale in Korean. Preserve technical identifiers, file paths, error codes, and stack \
frames exactly as supplied."""


def build_risk_user_prompt(
    issue_id: str,
    analysis: dict[str, object] | None,
    bug_context: dict[str, object] | None,
) -> str:
    """위험도 평가에 필요한 이슈 문맥을 하나의 사용자 메시지로 만든다."""

    return (
        "Assess the business risk of this issue.\n"
        + _json_dump(
            {
                "issue_id": issue_id,
                "bug_context": bug_context or {},
                "analysis": analysis or {},
            }
        )
    )


def _json_dump(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
