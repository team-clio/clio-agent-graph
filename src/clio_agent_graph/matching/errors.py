"""RM 실패를 오케스트레이터가 구분할 수 있게 하는 예외."""


class ReportMatchingError(RuntimeError):
    """RM 실행을 정상 MatchDecision으로 완료할 수 없을 때의 공통 오류."""


class IssueRetrievalNotConfiguredError(ReportMatchingError):
    """실제 RAG 하위 에이전트가 아직 연결되지 않았을 때의 설정 오류."""


class IssueRetrievalError(ReportMatchingError):
    """RAG 하위 에이전트가 한 번의 재시도 뒤에도 실패했을 때의 오류."""


class IssueMatchError(ReportMatchingError):
    """후보 비교 모델이 한 번의 재시도 뒤에도 실패했을 때의 오류."""


class IssueMatchOutputError(IssueMatchError):
    """후보 비교 모델의 출력을 신뢰할 수 없을 때의 오류."""
