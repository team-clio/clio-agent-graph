"""IA 실패를 Supervisor가 구분할 수 있게 하는 예외."""


class IssueAnalysisError(RuntimeError):
    """IA run을 정상 결과로 완료할 수 없을 때의 공통 오류."""


class CodeExplorerNotConfiguredError(IssueAnalysisError):
    """실제 Code Explorer subgraph가 연결되지 않은 설정 오류."""


class CodeExplorationError(IssueAnalysisError):
    """Code Explorer가 한 번의 재시도 뒤에도 실패한 오류."""


class JudgmentError(IssueAnalysisError):
    """판단 subagent가 한 번의 재시도 뒤에도 실패한 오류."""


class JudgmentOutputError(JudgmentError):
    """판단 subagent structured output을 신뢰할 수 없는 오류."""
