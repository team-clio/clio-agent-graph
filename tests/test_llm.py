import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from clio_agent_graph.context.tools.reports import load_report
from clio_agent_graph.runtime import llm
from clio_agent_graph.runtime.llm import LLMSettings, ModelOutputTruncatedError, ToolCallingAgent
from clio_agent_graph.runtime.structured_output import bind_structured_output
from clio_agent_graph.workflows.orchestration.agents.models import (
    IssueAnalysisOutput,
    MatchDecision,
    ResolutionPlan,
)


def test_openai_model_is_the_single_default_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "CLIO_MODEL",
        "CLIO_MODEL_BASE_URL",
        "CLIO_MODEL_API_KEY_ENV",
        "CLIO_MODEL_EXTRA_BODY",
        "CLIO_MODEL_MAX_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = LLMSettings.from_env()

    assert settings.provider == "openai"
    assert settings.model == "openai:gpt-4.1-mini"
    assert settings.base_url is None
    assert settings.max_tokens == 32768


def test_custom_endpoint_options_apply_to_the_selected_global_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIO_MODEL", "openai:local-model")
    monkeypatch.setenv("CLIO_MODEL_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("CLIO_MODEL_API_KEY_ENV", "LOCAL_LLM_KEY")
    monkeypatch.setenv("CLIO_MODEL_EXTRA_BODY", '{"thinking":{"type":"disabled"}}')
    monkeypatch.setenv("LOCAL_LLM_KEY", "test-key")
    captured: dict[str, object] = {}

    def fake_init_chat_model(model: str, **kwargs: object) -> object:
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init_chat_model)

    result = llm.build_chat_model()

    assert result is not None
    assert captured == {
        "model": "openai:local-model",
        "kwargs": {
            "callbacks": captured["kwargs"]["callbacks"],
            "base_url": "http://localhost:8000/v1",
            "api_key": "test-key",
            "extra_body": {"thinking": {"type": "disabled"}, "max_tokens": 32768},
            "model_kwargs": {"parallel_tool_calls": False},
        },
    }


def test_llm_requires_explicitly_selected_key_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIO_MODEL_API_KEY_ENV", "MISSING_PROVIDER_KEY")
    monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)

    with pytest.raises(RuntimeError, match="MISSING_PROVIDER_KEY"):
        LLMSettings.from_env()


def test_model_selection_requires_provider_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIO_MODEL", "model-without-provider")

    with pytest.raises(ValueError, match="provider:model"):
        LLMSettings.from_env()


class _AgentResponse(BaseModel):
    answer: str


def test_tool_calling_agent_builds_a_langchain_agent_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeAgent:
        def invoke(
            self, request: dict[str, object], *, config: dict[str, object]
        ) -> dict[str, object]:
            captured["request"] = request
            captured["config"] = config
            return {"structured_response": {"answer": "done"}}

    def fake_create_agent(**kwargs: object) -> FakeAgent:
        captured["kwargs"] = kwargs
        return FakeAgent()

    monkeypatch.setattr(llm, "build_chat_model", lambda: object())
    monkeypatch.setattr(llm, "create_agent", fake_create_agent)

    result = ToolCallingAgent(
        name="test_agent",
        system_prompt="test",
        tools=[load_report],
        response_model=_AgentResponse,
    ).invoke("test prompt")

    assert result == {"answer": "done"}
    assert captured["kwargs"] is not None
    assert captured["config"]["recursion_limit"] == 40
    assert len(captured["config"]["callbacks"]) == 1


def test_json_object_extracts_json_after_model_preamble() -> None:
    assert llm._json_object('Based on the evidence: {"answer":"done"}') == '{"answer": "done"}'


def test_issue_analysis_accepts_a_scored_root_cause_hypothesis() -> None:
    result = IssueAnalysisOutput.model_validate(
        {
            "issue_id": "ISSUE-1",
            "evidence_counts": {"code": 1},
            "root_cause_hypotheses": [
                {"hypothesis": "A required field is missing.", "confidence": 0.8}
            ],
            "confidence": 0.8,
        }
    )

    assert result.root_cause_hypotheses[0].confidence == 0.8


def test_issue_analysis_accepts_a_verified_fact() -> None:
    result = IssueAnalysisOutput.model_validate(
        {
            "issue_id": "ISSUE-1",
            "evidence_counts": {"code": 1},
            "root_cause_hypotheses": [],
            "facts": [{"fact": "The field is missing.", "verified": True}],
            "confidence": 0.8,
        }
    )

    assert result.facts[0].verified is True


def test_resolution_plan_accepts_a_structured_step() -> None:
    result = ResolutionPlan.model_validate(
        {
            "issue_id": "ISSUE-1",
            "steps": [{"id": 1, "action": "Validate input.", "details": "Require owner_id."}],
            "acceptance_criteria": ["Invalid requests return 400."],
        }
    )

    assert result.steps[0].action == "Validate input."


def test_resolution_plan_accepts_a_structured_risk() -> None:
    result = ResolutionPlan.model_validate(
        {
            "issue_id": "ISSUE-1",
            "steps": [],
            "acceptance_criteria": [],
            "risks": [{"risk": "The change can reject valid traffic.", "mitigation": "Add tests."}],
        }
    )

    assert result.risks[0].risk == "The change can reject valid traffic."


def test_match_decision_normalizes_qualitative_confidence() -> None:
    result = MatchDecision.model_validate(
        {"action": "create_new", "confidence": "high", "reason": "No candidates exist."}
    )

    assert result.confidence == 0.8


def test_openai_compatible_model_disables_parallel_tool_calls(monkeypatch):
    monkeypatch.setenv("CLIO_MODEL", "openai:deepseek-v4-flash")
    captured = {}

    def fake_init(model, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(llm, "init_chat_model", fake_init)
    llm.build_chat_model()
    assert captured["model_kwargs"]["parallel_tool_calls"] is False


def test_output_token_limit_is_configurable(monkeypatch):
    monkeypatch.setenv("CLIO_MODEL_MAX_TOKENS", "65536")

    assert LLMSettings.from_env().max_tokens == 65536


@pytest.mark.parametrize("value", ["0", "-1", "many"])
def test_output_token_limit_must_be_a_positive_integer(monkeypatch, value):
    monkeypatch.setenv("CLIO_MODEL_MAX_TOKENS", value)

    with pytest.raises(ValueError, match="CLIO_MODEL_MAX_TOKENS"):
        LLMSettings.from_env()


class _TruncatingChatModel(BaseChatModel):
    """요청마다 지정한 finish_reason으로 응답하는 fake provider model."""

    max_tokens: int | None = None
    finish_reason: str = "length"
    message: AIMessage = AIMessage(content="")

    @property
    def _llm_type(self) -> str:
        return "truncating"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.message.model_copy(
            update={"response_metadata": {"finish_reason": self.finish_reason}}
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def _use_fake_provider(monkeypatch, **fields):
    monkeypatch.setenv("CLIO_MODEL", "fake:model")
    monkeypatch.setenv("CLIO_MODEL_MAX_TOKENS", "100")
    for name in ("CLIO_MODEL_BASE_URL", "CLIO_MODEL_API_KEY_ENV", "CLIO_MODEL_EXTRA_BODY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        llm,
        "init_chat_model",
        lambda model, **kwargs: _TruncatingChatModel(**kwargs, **fields),
    )


def test_truncated_structured_output_fails_as_truncation_not_as_invalid_output(monkeypatch):
    class Answer(BaseModel):
        answer: str

    truncated_call = AIMessage(
        content="",
        invalid_tool_calls=[
            {"id": "call", "name": "Answer", "args": '{"answer": "tru', "error": None}
        ],
    )
    _use_fake_provider(monkeypatch, message=truncated_call)
    model = bind_structured_output(llm.build_chat_model(), Answer)

    with pytest.raises(ModelOutputTruncatedError, match="100 token output limit"):
        model.invoke("answer")


def test_truncated_agent_response_fails_as_truncation(monkeypatch):
    class Answer(BaseModel):
        answer: str

    _use_fake_provider(monkeypatch)
    agent = ToolCallingAgent(name="test", system_prompt="test", tools=[], response_model=Answer)

    with pytest.raises(ModelOutputTruncatedError):
        agent.invoke("answer")


def test_completed_response_passes_the_truncation_guard(monkeypatch):
    _use_fake_provider(monkeypatch, finish_reason="stop", message=AIMessage(content="done"))

    assert llm.build_chat_model().invoke("answer").content == "done"


def test_compatible_endpoint_receives_the_standard_max_tokens_field(monkeypatch):
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("CLIO_MODEL", "openai:deepseek-v4-flash")
    monkeypatch.setenv("CLIO_MODEL_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("CLIO_MODEL_API_KEY_ENV", "TEST_KEY")
    monkeypatch.setenv("TEST_KEY", "test-key")
    monkeypatch.setenv("CLIO_MODEL_MAX_TOKENS", "4096")
    monkeypatch.delenv("CLIO_MODEL_EXTRA_BODY", raising=False)

    payload = llm.build_chat_model()._get_request_payload([("user", "hi")])

    assert payload["extra_body"]["max_tokens"] == 4096
    assert "max_completion_tokens" not in payload


def test_official_openai_endpoint_receives_max_completion_tokens(monkeypatch):
    pytest.importorskip("langchain_openai")
    monkeypatch.setenv("CLIO_MODEL", "openai:gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CLIO_MODEL_MAX_TOKENS", "4096")
    for name in ("CLIO_MODEL_BASE_URL", "CLIO_MODEL_API_KEY_ENV", "CLIO_MODEL_EXTRA_BODY"):
        monkeypatch.delenv(name, raising=False)

    payload = llm.build_chat_model()._get_request_payload([("user", "hi")])

    assert payload["max_completion_tokens"] == 4096
