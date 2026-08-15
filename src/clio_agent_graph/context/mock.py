"""아직 영속 경계가 없는 memory sync용 Mock 구현.

TODO: document/repository/code revision commit 경계를 실제 서비스로 교체한다.
"""

from typing import Any


class MockClioService:
    """동기화 그래프 검증을 위한 결정적이고 부작용 없는 Mock."""

    def commit_sync(
        self, kind: str, project_id: str, identifier: str, revision: str | None
    ) -> dict[str, Any]:
        # TODO: 실제 index update와 RDBMS revision commit을 트랜잭션/멱등성 키와 함께 구현.
        return {
            "kind": kind,
            "project_id": project_id,
            "identifier": identifier,
            "revision": revision,
            "status": "mock_committed",
        }


mock_service = MockClioService()
