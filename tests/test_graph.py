import pytest
from pydantic import ValidationError

from clio_agent_graph.graph import graph


def test_routes_analyze_issue_directly_to_reusable_analysis_graph() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-1",
                "request_type": "analyze_issue",
                "project_id": "PROJECT-1",
                "payload": {"issue_id": "ISSUE-1"},
            },
            "document_evidence": [{"id": "DOC-1"}],
            "code_evidence": [{"id": "CODE-1"}],
            "history_evidence": [{"id": "HISTORY-1"}],
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"
    assert result["result"]["issue_id"] == "ISSUE-1"
    assert result["result"]["analysis"]["evidence_counts"] == {
        "documents": 1,
        "code": 1,
        "history": 1,
    }
    assert "load_and_normalize_report" not in result["completed_nodes"]
    assert result["completed_nodes"]["prepare_analysis"] is True


def test_new_report_reuses_issue_analysis_graph() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-2",
                "request_type": "process_report",
                "project_id": "PROJECT-1",
                "payload": {"report_id": "REPORT-1"},
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "analysis_completed"
    assert result["result"]["issue_id"] == "ISSUE-FROM-REPORT-1"
    assert result["completed_nodes"]["match_report"] is True
    assert result["completed_nodes"]["prepare_analysis"] is True
    assert result["completed_nodes"]["save_analysis"] is True


def test_existing_issue_match_skips_issue_analysis_graph() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-3",
                "request_type": "process_report",
                "project_id": "PROJECT-1",
                "payload": {"report_id": "REPORT-2"},
            },
            "issue_candidates": [
                {
                    "issue_id": "ISSUE-EXISTING",
                    "confidence": 0.97,
                }
            ],
        }
    )

    assert result["status"] == "completed"
    assert result["result"] == {
        "action": "link_existing",
        "report_id": "REPORT-2",
        "issue_id": "ISSUE-EXISTING",
    }
    assert "prepare_analysis" not in result["completed_nodes"]


def test_uncertain_match_finishes_as_needs_review() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-4",
                "request_type": "process_report",
                "project_id": "PROJECT-1",
                "payload": {"report_id": "REPORT-3"},
            },
            "issue_candidates": [
                {
                    "issue_id": "ISSUE-CANDIDATE",
                    "confidence": 0.55,
                    "requires_review": True,
                }
            ],
        }
    )

    assert result["status"] == "needs_review"
    assert result["result"]["action"] == "needs_review"
    assert "prepare_analysis" not in result["completed_nodes"]


def test_rejects_unknown_request_type_before_routing() -> None:
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        graph.invoke(
            {
                "request": {
                    "request_id": "REQ-5",
                    "request_type": "unknown",
                    "project_id": "PROJECT-1",
                    "payload": {},
                }
            }
        )


def test_routes_document_event_to_mock_sync_graph() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-6",
                "request_type": "document_added",
                "project_id": "PROJECT-1",
                "payload": {"document_id": "DOC-1", "revision": "REV-1"},
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "document_synced"
    assert result["completed_nodes"]["update_document_index"] is True


def test_routes_repository_change_to_incremental_mock_sync_graph() -> None:
    result = graph.invoke(
        {
            "request": {
                "request_id": "REQ-7",
                "request_type": "repository_changed",
                "project_id": "PROJECT-1",
                "payload": {
                    "repository_id": "REPO-1",
                    "branch": "main",
                    "before_commit": "abc123",
                    "after_commit": "def456",
                },
            }
        }
    )

    assert result["status"] == "completed"
    assert result["result"]["action"] == "code_change_synced"
    assert result["completed_nodes"]["validate_code_change"] is True
