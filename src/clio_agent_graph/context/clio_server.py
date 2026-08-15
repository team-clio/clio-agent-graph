"""Clio Server internal API port와 동기 HTTP adapter."""

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_SERVER_URL = "http://localhost:8080"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 1024 * 1024


class ClioServerError(RuntimeError):
    """Clio Server 요청이 실패했거나 유효하지 않은 응답을 반환한 오류."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class WorkflowStart:
    """Server workflow 등록 결과와 replay 여부."""

    workflow_run_id: int
    status: str
    result: dict[str, object] | None = None


class ClioServer(Protocol):
    """오케스트레이션 노드가 사용하는 Server API 계약."""

    def start_workflow(
        self,
        project_id: str,
        request_id: str,
        request_type: str,
        request_payload: dict[str, object],
    ) -> WorkflowStart: ...

    def complete_workflow(
        self, project_id: str, workflow_run_id: int, result: dict[str, object]
    ) -> None: ...

    def fail_workflow(
        self,
        project_id: str,
        workflow_run_id: int,
        *,
        failure_code: str,
        failure_message: str,
    ) -> None: ...

    def load_bug(self, project_id: str, bug_id: str) -> dict[str, Any]: ...

    def load_issue_representative_bug(
        self, project_id: str, issue_id: str
    ) -> dict[str, Any]: ...

    def create_issue(
        self,
        project_id: str,
        workflow_run_id: int,
        bug_id: str,
        confidence: float,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]: ...

    def link_bug(
        self,
        project_id: str,
        workflow_run_id: int,
        bug_id: str,
        issue_id: str,
        confidence: float,
    ) -> dict[str, Any]: ...

    def save_analysis(
        self,
        project_id: str,
        workflow_run_id: int,
        issue_id: str,
        issue_analysis: dict[str, object],
    ) -> dict[str, Any]: ...


class ClioServerClient:
    """`CLIO_SERVER_URL`을 사용하는 Clio Server internal API client."""

    def __init__(self, base_url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        normalized_url = base_url.strip().rstrip("/")
        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CLIO_SERVER_URL must be an HTTP URL.")
        if timeout_seconds <= 0:
            raise ValueError("CLIO_SERVER_TIMEOUT_SECONDS must be greater than zero.")
        self._base_url = normalized_url
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "ClioServerClient":
        return cls(
            os.getenv("CLIO_SERVER_URL", DEFAULT_SERVER_URL),
            timeout_seconds=float(
                os.getenv("CLIO_SERVER_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
            ),
        )

    def start_workflow(
        self,
        project_id: str,
        request_id: str,
        request_type: str,
        request_payload: dict[str, object],
    ) -> WorkflowStart:
        run = self._request(
            "POST",
            f"/internal-api/v1/projects/{int(project_id)}/workflow-runs",
            {
                "request_id": request_id,
                "request_type": request_type,
                "request_payload": request_payload,
            },
        )
        workflow_run_id = int(run["id"])
        status = run.get("status", "PENDING")
        if status == "RUNNING":
            raise ClioServerError(f"Workflow {workflow_run_id} is already running.")
        if status == "COMPLETED":
            result = run.get("result_snapshot")
            return WorkflowStart(
                workflow_run_id=workflow_run_id,
                status=status,
                result=result if isinstance(result, dict) else {},
            )
        if status != "PENDING":
            raise ClioServerError(f"Workflow {workflow_run_id} cannot start from {status}.")
        self._request(
            "PATCH",
            f"/internal-api/v1/projects/{int(project_id)}/workflow-runs/{workflow_run_id}",
            {"status": "RUNNING"},
        )
        return WorkflowStart(workflow_run_id=workflow_run_id, status="RUNNING")

    def complete_workflow(
        self, project_id: str, workflow_run_id: int, result: dict[str, object]
    ) -> None:
        self._request(
            "PATCH",
            f"/internal-api/v1/projects/{int(project_id)}/workflow-runs/{workflow_run_id}",
            {
                "status": "COMPLETED",
                "latest_checkpoint": {"node": "complete_workflow"},
                "result_snapshot": result,
            },
        )

    def fail_workflow(
        self,
        project_id: str,
        workflow_run_id: int,
        *,
        failure_code: str,
        failure_message: str,
    ) -> None:
        self._request(
            "PATCH",
            f"/internal-api/v1/projects/{int(project_id)}/workflow-runs/{workflow_run_id}",
            {
                "status": "FAILED",
                "failure_code": failure_code,
                "failure_message": failure_message[:2000],
            },
        )

    def load_bug(self, project_id: str, bug_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/internal-api/v1/projects/{int(project_id)}/bugs/{int(bug_id)}"
        )

    def load_issue_representative_bug(self, project_id: str, issue_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            (
                f"/internal-api/v1/projects/{int(project_id)}/issues/"
                f"{int(issue_id)}/bugs/representative"
            ),
        )

    def create_issue(
        self,
        project_id: str,
        workflow_run_id: int,
        bug_id: str,
        confidence: float,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, object] = {
            "workflow_run_id": workflow_run_id,
            "bug_id": int(bug_id),
            "confidence": confidence,
        }
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        return self._request(
            "POST",
            f"/internal-api/v1/projects/{int(project_id)}/issues",
            payload,
        )

    def link_bug(
        self,
        project_id: str,
        workflow_run_id: int,
        bug_id: str,
        issue_id: str,
        confidence: float,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/internal-api/v1/projects/{int(project_id)}/issues/{int(issue_id)}/bugs",
            {
                "workflow_run_id": workflow_run_id,
                "bug_id": int(bug_id),
                "confidence": confidence,
            },
        )

    def save_analysis(
        self,
        project_id: str,
        workflow_run_id: int,
        issue_id: str,
        issue_analysis: dict[str, object],
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            (
                f"/internal-api/v1/projects/{int(project_id)}/workflow-runs/"
                f"{workflow_run_id}/analysis-result"
            ),
            {
                "issue_id": int(issue_id),
                "previous_analysis_result_id": None,
                "issue_analysis": issue_analysis,
            },
        )

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        request = Request(f"{self._base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            detail = _read_error_message(error)
            raise ClioServerError(detail, status_code=error.code) from error
        except URLError as error:
            raise ClioServerError(f"Clio Server is unavailable: {error.reason}") from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ClioServerError("Clio Server response exceeds the size limit.")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClioServerError("Clio Server returned invalid JSON.") from error
        if not isinstance(decoded, dict):
            raise ClioServerError("Clio Server returned an unexpected response shape.")
        return decoded


def _read_error_message(error: HTTPError) -> str:
    try:
        payload = json.loads(error.read(MAX_RESPONSE_BYTES))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"Clio Server request failed with HTTP {error.code}."
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"]
    return f"Clio Server request failed with HTTP {error.code}."
