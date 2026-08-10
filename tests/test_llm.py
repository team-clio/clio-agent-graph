import pytest
from pydantic import BaseModel

from clio_agent_graph.context.tools.reports import load_report
from clio_agent_graph.runtime import llm
from clio_agent_graph.runtime.llm import LLMSettings, ToolCallingAgent
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
    ):
        monkeypatch.delenv(name, raising=False)

    settings = LLMSettings.from_env()

    assert settings.provider == "openai"
    assert settings.model == "openai:gpt-4.1-mini"
    assert settings.base_url is None


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
            "base_url": "http://localhost:8000/v1",
            "api_key": "test-key",
            "extra_body": {"thinking": {"type": "disabled"}},
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
        def invoke(self, request: dict[str, object]) -> dict[str, object]:
            captured["request"] = request
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
