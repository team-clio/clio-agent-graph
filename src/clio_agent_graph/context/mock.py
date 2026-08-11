"""개발용 외부 의존성 Mock 구현.

TODO: API Server, Vector DB, RDBMS, Git 연동이 준비되면 이 구현을 실제
서비스 어댑터로 교체하고, 그래프 실행 단위에서 의존성을 주입한다.
"""

from typing import Any


class MockClioService:
    """그래프 상위 계층을 검증하기 위한 결정적이고 부작용 없는 Mock."""

    def load_report(self, project_id: str, report_id: str) -> dict[str, Any]:
        # TODO: API Server에서 원본 report와 원문 evidence를 조회하고,
        # LLM structured output으로 정규화.
        return {
            "report_id": report_id,
            "project_id": project_id,
            "symptom": "Submitting a saved-search form returns HTTP 500 instead of results.",
            "environment": {
                "application_version": "2026.08.03",
                "browser": "Chrome 138",
                "endpoint": "POST /api/saved-searches/{search_id}/run",
            },
            "reproduction_steps": [
                "Create a saved search with at least one filter.",
                "Open the saved search and select Run.",
                "Observe that the request returns HTTP 500.",
            ],
            "evidence": [
                {
                    "source": "application-log",
                    "content": "KeyError: owner_id while resolving the saved search request.",
                }
            ],
        }

    def search_issue_candidates(
        self, project_id: str, report: dict[str, Any]
    ) -> list[dict[str, Any]]:
        # TODO: RDBMS, keyword 및 Vector 검색을 조합하고 후보를 rerank.
        return []

    def apply_match_decision(
        self, project_id: str, report_id: str, decision: dict[str, Any]
    ) -> dict[str, Any]:
        # TODO: API Server 호출, idempotency key 및 revision 충돌 처리를 구현.
        if decision["action"] == "create_new":
            return {"issue_id": f"ISSUE-FROM-{report_id}"}
        return {"issue_id": decision.get("issue_id")}

    def save_analysis(self, project_id: str, issue_id: str) -> None:
        # TODO: analysis, resolution plan, evidence IDs와 snapshot revision을 API Server에 저장.
        return None

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
