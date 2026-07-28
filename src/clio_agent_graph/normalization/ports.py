"""NM 도메인이 외부 모델 구현에 요구하는 최소 인터페이스."""

from typing import Protocol

from clio_agent_graph.normalization.models import NormalizationDraft


class NormalizationModel(Protocol):
    """BugReport 텍스트에서 구조화된 사실을 추출하는 모델 인터페이스.

    Python의 Protocol은 Java의 interface처럼 구현 클래스가 지켜야 할 메서드 모양을 정의한다.
    클래스를 명시적으로 상속하지 않아도 같은 메서드를 제공하면 이 타입으로 사용할 수 있다.
    """

    def extract(
        self,
        report_text: str,
        *,
        correction_feedback: str | None = None,
    ) -> NormalizationDraft:
        """리포트를 구조화하고, 필요하면 이전 검증 오류를 반영해 교정한다."""

        ...


class NormalizationOutputError(ValueError):
    """모델 응답을 NormalizationDraft로 검증할 수 없을 때 발생하는 오류."""
