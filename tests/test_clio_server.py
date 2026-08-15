import io
import json
from urllib.error import HTTPError

import pytest

from clio_agent_graph.context import clio_server
from clio_agent_graph.context.clio_server import ClioServerClient, ClioServerError


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.payload


def test_start_workflow_registers_and_transitions_to_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    responses = iter([FakeResponse({"id": 501, "status": "PENDING"}), FakeResponse({"id": 501})])

    def fake_urlopen(request, *, timeout):
        requests.append((request, timeout))
        return next(responses)

    monkeypatch.setattr(clio_server, "urlopen", fake_urlopen)
    client = ClioServerClient("http://localhost:8080", timeout_seconds=3)

    started = client.start_workflow("3", "REQ-1", "process_report", {"bug_id": "72"})

    assert started.workflow_run_id == 501
    assert started.status == "RUNNING"
    assert [request.method for request, _ in requests] == ["POST", "PATCH"]
    assert requests[0][0].full_url.endswith("/projects/3/workflow-runs")
    assert json.loads(requests[0][0].data) == {
        "request_id": "REQ-1",
        "request_type": "process_report",
        "request_payload": {"bug_id": "72"},
    }
    assert json.loads(requests[1][0].data) == {"status": "RUNNING"}
    assert requests[0][1] == 3


def test_completed_workflow_replay_returns_snapshot_without_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def fake_urlopen(request, *, timeout):
        requests.append(request)
        return FakeResponse(
            {
                "id": 501,
                "status": "COMPLETED",
                "result_snapshot": {"action": "link_existing", "issue_id": 19},
            }
        )

    monkeypatch.setattr(clio_server, "urlopen", fake_urlopen)

    started = ClioServerClient("http://localhost:8080").start_workflow(
        "3", "REQ-1", "process_report", {"bug_id": "72"}
    )

    assert started.status == "COMPLETED"
    assert started.result == {"action": "link_existing", "issue_id": 19}
    assert len(requests) == 1


def test_create_issue_sends_workflow_and_bug_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        return FakeResponse({"issue_id": 19, "bug_id": 72, "issue_created": True})

    monkeypatch.setattr(clio_server, "urlopen", fake_urlopen)
    client = ClioServerClient("http://localhost:8080")

    result = client.create_issue("3", 501, "72", 0.81)

    request = captured["request"]
    assert request.full_url.endswith("/projects/3/issues")
    assert json.loads(request.data) == {
        "workflow_run_id": 501,
        "bug_id": 72,
        "confidence": 0.81,
    }
    assert result["issue_id"] == 19


def test_create_issue_sends_korean_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        return FakeResponse({"issue_id": 19, "bug_id": 72, "issue_created": True})

    monkeypatch.setattr(clio_server, "urlopen", fake_urlopen)

    ClioServerClient("http://localhost:8080").create_issue(
        "3",
        501,
        "72",
        0.81,
        title="결제 승인에 실패합니다",
        description="## 증상\n결제 승인 요청이 실패합니다.",
    )

    assert json.loads(captured["request"].data)["title"] == "결제 승인에 실패합니다"
    assert json.loads(captured["request"].data)["description"].startswith("## 증상")


def test_loads_representative_bug_for_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        return FakeResponse({"bug_id": 72, "error_type": "PaymentApprovalException"})

    monkeypatch.setattr(clio_server, "urlopen", fake_urlopen)

    result = ClioServerClient("http://localhost:8080").load_issue_representative_bug("3", "19")

    assert captured["request"].full_url.endswith("/projects/3/issues/19/bugs/representative")
    assert result["bug_id"] == 72


def test_http_error_preserves_server_message(monkeypatch: pytest.MonkeyPatch) -> None:
    body = io.BytesIO(json.dumps({"message": "workflow must be RUNNING"}).encode())

    def fake_urlopen(request, *, timeout):
        raise HTTPError(request.full_url, 409, "Conflict", {}, body)

    monkeypatch.setattr(clio_server, "urlopen", fake_urlopen)
    client = ClioServerClient("http://localhost:8080")

    with pytest.raises(ClioServerError, match="workflow must be RUNNING") as error:
        client.create_issue("3", 501, "72", 0.81)

    assert error.value.status_code == 409


@pytest.mark.parametrize("url", ["", "localhost:8080", "ftp://localhost"])
def test_rejects_invalid_server_url(url: str) -> None:
    with pytest.raises(ValueError, match="HTTP URL"):
        ClioServerClient(url)
