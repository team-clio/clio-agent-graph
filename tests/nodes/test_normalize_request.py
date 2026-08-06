import pytest
from langchain_core.messages import HumanMessage

from clio_agent_graph.nodes import normalize_request


def test_prefers_explicit_request() -> None:
    result = normalize_request(
        {
            "request": "Explicit request",
            "messages": [HumanMessage(content="Message request")],
        }
    )

    assert result == {"request": "Explicit request"}


def test_uses_latest_human_message() -> None:
    result = normalize_request(
        {
            "messages": [
                HumanMessage(content="First request"),
                HumanMessage(content="Latest request"),
            ]
        }
    )

    assert result == {"request": "Latest request"}


def test_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="non-empty request"):
        normalize_request({})
