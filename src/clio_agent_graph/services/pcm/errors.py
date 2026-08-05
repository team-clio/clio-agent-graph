"""PCM 도메인에서 호출자가 처리할 수 있는 오류."""


class PCMError(Exception):
    """모든 PCM 애플리케이션 오류의 기반 클래스."""


class PCMValidationError(PCMError, ValueError):
    """Knowledge 변경이나 조회 입력이 도메인 규칙을 위반했다."""


class PCMRevisionConflict(PCMError):
    """변경안의 base revision이 현재 프로젝트 revision과 다르다."""

    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"PCM revision conflict: expected {expected}, actual {actual}.")


class KnowledgeNotFoundError(PCMError, LookupError):
    """요청한 snapshot에서 Knowledge를 찾을 수 없다."""


class KnowledgeModelOutputError(PCMError):
    """Knowledge LLM 응답이 요구된 structured output을 만족하지 못했다."""
