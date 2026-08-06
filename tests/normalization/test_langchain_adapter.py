from typing import Any

import pytest
from langchain_core.tools import tool

from clio_agent_graph.normalization import NormalizationOutputError
from clio_agent_graph.normalization.langchain_adapter import LangChainNormalizationModel
from clio_agent_graph.normalization.models import NormalizationDraft


class FakeStructuredModel:
    """invoke 입력을 기록하고 준비된 structured output을 반환하는 runnable."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[list[Any]] = []

    def invoke(self, messages: list[Any]) -> Any:
        self.calls.append(messages)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeChatModel:
    """with_structured_output에 전달된 Pydantic schema를 기록한다."""

    def __init__(self, structured_model: FakeStructuredModel) -> None:
        self.structured_model = structured_model
        self.schemas: list[type] = []

    def with_structured_output(self, schema: type) -> FakeStructuredModel:
        self.schemas.append(schema)
        return self.structured_model


def test_model_is_created_lazily_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    structured_model = FakeStructuredModel({"observed_behavior": "결제 요청이 실패한다."})
    chat_model = FakeChatModel(structured_model)
    build_calls: list[bool] = []

    def fake_build_chat_model() -> FakeChatModel:
        build_calls.append(True)
        return chat_model

    monkeypatch.setattr(
        "clio_agent_graph.normalization.langchain_adapter.build_chat_model",
        fake_build_chat_model,
    )
    adapter = LangChainNormalizationModel()

    assert build_calls == []

    first = adapter.extract("first report")
    second = adapter.extract("second report")

    assert first.observed_behavior == "결제 요청이 실패한다."
    assert second.observed_behavior == "결제 요청이 실패한다."
    assert build_calls == [True]
    assert chat_model.schemas == [NormalizationDraft]


def test_adapter_passes_correction_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured_model = FakeStructuredModel({})
    chat_model = FakeChatModel(structured_model)

    monkeypatch.setattr(
        "clio_agent_graph.normalization.langchain_adapter.build_chat_model",
        lambda: chat_model,
    )

    LangChainNormalizationModel().extract(
        "report",
        correction_feedback="expected_behavior must be null",
    )

    human_message = structured_model.calls[0][1]
    assert "expected_behavior must be null" in str(human_message.content)


def test_invalid_structured_result_is_wrapped_for_service_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured_model = FakeStructuredModel({"unexpected_field": "not allowed"})
    chat_model = FakeChatModel(structured_model)
    monkeypatch.setattr(
        "clio_agent_graph.normalization.langchain_adapter.build_chat_model",
        lambda: chat_model,
    )

    with pytest.raises(NormalizationOutputError, match="Extra inputs are not permitted"):
        LangChainNormalizationModel().extract("report")


def test_provider_error_is_not_wrapped_as_output_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured_model = FakeStructuredModel(RuntimeError("provider unavailable"))
    chat_model = FakeChatModel(structured_model)
    monkeypatch.setattr(
        "clio_agent_graph.normalization.langchain_adapter.build_chat_model",
        lambda: chat_model,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        LangChainNormalizationModel().extract("report")


def test_adapter_uses_autonomous_agent_when_tools_are_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @tool
    def read_report_attachment(attachment_id: str) -> dict[str, str]:
        """Read a report attachment."""

        return {"attachment_id": attachment_id}

    captured: dict[str, Any] = {}

    class FakeToolAgent:
        last_tool_calls = [
            {
                "name": "read_report_attachment",
                "arguments": {"attachment_id": "LOG-1"},
                "call_id": "call-1",
            }
        ]

        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def invoke(self, prompt: str) -> NormalizationDraft:
            assert "Normalize the following bug report" in prompt
            return NormalizationDraft(observed_behavior="첨부 로그에서 timeout을 확인했다.")

    monkeypatch.setattr(
        "clio_agent_graph.normalization.langchain_adapter.build_chat_model",
        lambda: object(),
    )
    monkeypatch.setattr(
        "clio_agent_graph.normalization.langchain_adapter.StructuredToolAgent",
        FakeToolAgent,
    )

    adapter = LangChainNormalizationModel(
        tools=[read_report_attachment],
    )
    result = adapter.extract("attachment_id=LOG-1")

    assert result.observed_behavior == "첨부 로그에서 timeout을 확인했다."
    assert captured["tools"] == [read_report_attachment]
    assert adapter.last_tool_calls[0]["name"] == "read_report_attachment"
