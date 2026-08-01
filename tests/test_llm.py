import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from clio_agent_graph import llm
from clio_agent_graph.llm import LLMSettings, ToolCallingAgent
from clio_agent_graph.tools.reports import load_report


def test_deepseek_is_the_default_provider_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "CLIO_LLM_PROVIDER",
        "CLIO_LLM_MODEL",
        "CLIO_LLM_BASE_URL",
        "CLIO_LLM_API_KEY_ENV",
        "DEEPSEEK_API_KEY",
        "CLIO_AGENT_MODE",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = LLMSettings.from_env()

    assert settings.provider == "deepseek"
    assert settings.model == "deepseek-chat"
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.use_llm is False


def test_openai_compatible_provider_uses_environment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIO_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLIO_LLM_MODEL", "local-model")
    monkeypatch.setenv("CLIO_LLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("CLIO_LLM_API_KEY_ENV", "LOCAL_LLM_KEY")
    monkeypatch.setenv("LOCAL_LLM_KEY", "test-key")

    settings = LLMSettings.from_env()

    assert settings.use_llm is True
    assert settings.model == "local-model"


def test_explicit_llm_mode_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIO_AGENT_MODE", "llm")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="API key"):
        _ = LLMSettings.from_env().use_llm


class _AgentResponse(BaseModel):
    answer: str


def test_tool_calling_agent_builds_a_langchain_agent_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    captured: dict[str, object] = {}

    class FakeAgent:
        def invoke(self, request: dict[str, object]) -> dict[str, object]:
            captured["request"] = request
            return {"messages": [AIMessage(content='{"answer":"done"}')]}

    def fake_create_agent(**kwargs: object) -> FakeAgent:
        captured["kwargs"] = kwargs
        return FakeAgent()

    monkeypatch.setattr(llm, "build_chat_model", lambda settings: object())
    monkeypatch.setattr(llm, "create_agent", fake_create_agent)

    result = ToolCallingAgent(
        name="test_agent",
        system_prompt="test",
        tools=[load_report],
        response_model=_AgentResponse,
    ).invoke("test prompt")

    assert result == {"answer": "done"}
    assert captured["kwargs"] is not None
