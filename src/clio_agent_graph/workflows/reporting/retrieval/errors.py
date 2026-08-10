"""Issue Retrieval Agent가 정상 0건과 기술 실패를 구분하는 예외."""


class RetrievalAgentError(RuntimeError):
    """Retrieval Agent 실행 자체가 완료되지 못했음을 나타낸다."""


class RetrievalConfigurationError(RetrievalAgentError):
    """DB·embedding 모델 같은 필수 운영 설정이 없다."""


class RetrievalIndexNotReadyError(RetrievalAgentError):
    """검색 대상 Bug 중 아직 compatible active index가 없는 Bug가 있다."""


class RetrievalOperationError(RetrievalAgentError):
    """DB나 embedding provider가 한 번의 재시도 후에도 실패했다."""


class RetrievalDataError(RetrievalAgentError):
    """식별자 관계나 저장 데이터가 공개 계약과 일치하지 않는다."""
