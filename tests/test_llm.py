import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from clio_agent_graph import llm
from clio_agent_graph.agents.models import IssueAnalysisOutput, MatchDecision, ResolutionPlan
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
    ):
        monkeypatch.delenv(name, raising=False)

    settings = LLMSettings.from_env()

    assert settings.provider == "deepseek"
    assert settings.model == "deepseek-chat"
    assert settings.base_url == "https://api.deepseek.com"
    with pytest.raises(RuntimeError, match="API key"):
        _ = settings.use_llm


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


def test_llm_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
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
