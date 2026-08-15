import pytest
from pydantic import ValidationError

from clio_agent_graph.workflows.analysis.risk import (
    RiskAssessment,
    RiskFactor,
    map_risk_to_priority,
)


@pytest.mark.parametrize(
    ("risk_score", "expected"),
    [
        (0, "P4"),
        (29, "P4"),
        (30, "P3"),
        (49, "P3"),
        (50, "P2"),
        (69, "P2"),
        (70, "P1"),
        (84, "P1"),
        (85, "P0"),
        (100, "P0"),
        (42, "P3"),
        (77, "P1"),
    ],
)
def test_map_risk_to_priority_bands(risk_score: int, expected: str) -> None:
    assert map_risk_to_priority(risk_score) == expected


@pytest.mark.parametrize("risk_score", [-1, 101, 1000])
def test_map_risk_to_priority_rejects_out_of_range(risk_score: int) -> None:
    with pytest.raises(ValueError):
        map_risk_to_priority(risk_score)


@pytest.mark.parametrize("risk_score", [1.5, "80", None, True])
def test_map_risk_to_priority_rejects_non_integer(risk_score: object) -> None:
    with pytest.raises(ValueError):
        map_risk_to_priority(risk_score)  # type: ignore[arg-type]


def test_risk_assessment_derives_priority_from_score() -> None:
    assessment = RiskAssessment(
        risk_score=72,
        factors=[RiskFactor(name="영향 범위", score=80, rationale="결제 경로 전체에 영향을 준다.")],
        rationale="핵심 결제 기능이 차단되어 우회가 불가능하다.",
    )

    assert assessment.priority == "P1"


def test_risk_assessment_rejects_score_above_100() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(
            risk_score=101,
            factors=[RiskFactor(name="심각도", score=100, rationale="치명적이다.")],
            rationale="잘못된 점수",
        )


def test_risk_assessment_requires_at_least_one_factor() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(risk_score=50, factors=[], rationale="요인이 없다.")
