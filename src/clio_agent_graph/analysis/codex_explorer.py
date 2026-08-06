"""Codex CLI가 실제 repository를 읽어 IA Evidence 후보를 만드는 Code Explorer."""

import json
import os
from pathlib import Path

from clio_agent_graph.analysis.errors import CodeExplorerNotConfiguredError
from clio_agent_graph.analysis.models import ExplorationRequest, ExplorationResponse
from clio_agent_graph.codex_exec import CodexExecStructuredInvoker

SYSTEM_PROMPT = """당신은 Issue Analyzer의 읽기 전용 Codebase Explorer다.
제공된 저장소를 실제로 탐색하고 질문에 직접 관련된 근거만 반환한다.
추측을 Evidence로 만들지 말고, code_snapshot은 파일에서 확인한 원문 1~10줄이어야 한다.
file_path는 작업 디렉터리 기준 상대 경로, line metadata는 실제 1-based 줄 번호를 사용한다.
candidate_key는 이번 응답 안에서 고유해야 한다.
관계의 source_ref와 target_ref는 기존 Evidence ID 또는 이번 candidate_key만 참조한다.
관련 코드를 찾지 못하면 candidates와 relations를 빈 목록으로 반환한다.
파일을 수정하거나 명령으로 repository 상태를 바꾸지 않는다."""


class CodexCodeExplorer:
    """지정된 local codebase에서 Codex를 읽기 전용 탐색 agent로 실행한다."""

    def __init__(
        self,
        codebase_path: str | Path | None = None,
        invoker: CodexExecStructuredInvoker | None = None,
    ) -> None:
        configured_path = codebase_path or os.getenv("CLIO_CODEBASE_PATH")
        self._codebase_path = (
            Path(configured_path).expanduser().resolve() if configured_path else None
        )
        self._invoker = invoker or CodexExecStructuredInvoker()

    def __call__(self, request: ExplorationRequest) -> ExplorationResponse:
        """IA 탐색 요청을 JSON으로 전달하고 실제 코드 snapshot을 반환한다."""

        if self._codebase_path is None:
            raise CodeExplorerNotConfiguredError("CLIO_CODEBASE_PATH is not configured.")
        if not self._codebase_path.is_dir():
            raise CodeExplorerNotConfiguredError(
                f"CLIO_CODEBASE_PATH does not exist: {self._codebase_path}"
            )
        return self._invoker.invoke(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
            output_type=ExplorationResponse,
            working_directory=self._codebase_path,
        )
