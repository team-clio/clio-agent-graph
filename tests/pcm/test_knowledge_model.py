import pytest
from langchain_core.messages import AIMessage

from clio_agent_graph.llm import LLMSettings
from clio_agent_graph.services.pcm import knowledge_model
from clio_agent_graph.services.pcm.knowledge_model import OpenAICompatibleKnowledgeModel
from clio_agent_graph.services.pcm.models import DocumentSourceUnit


@pytest.mark.asyncio
async def test_knowledge_model_reuses_existing_clio_llm_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIO_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLIO_LLM_MODEL", "knowledge-model")
    monkeypatch.setenv("CLIO_LLM_BASE_URL", "https://models.example.test/v1")
    monkeypatch.setenv("CLIO_LLM_API_KEY_ENV", "KNOWLEDGE_MODEL_KEY")
    monkeypatch.setenv("KNOWLEDGE_MODEL_KEY", "test-key")
    captured: dict[str, object] = {}

    class FakeChatModel:
        async def ainvoke(self, prompt: str) -> AIMessage:
            captured["prompt"] = prompt
            return AIMessage(
                content="""
                {
                  "topics": [{
                    "topic_key": "permissions",
                    "title": "Permissions",
                    "knowledge_type": "domain_rule",
                    "summary": "Edit permissions.",
                    "source_unit_ids": ["DSU-1"],
                    "suggested_search_queries": ["edit permissions"]
                  }]
                }
                """
            )

    def fake_build_chat_model(settings: object) -> FakeChatModel:
        captured["settings"] = settings
        return FakeChatModel()

    monkeypatch.setattr(knowledge_model, "build_chat_model", fake_build_chat_model)
    unit = DocumentSourceUnit(
        source_unit_id="DSU-1",
        document_id="requirements",
        source_revision="1",
        heading_path=("Permissions",),
        content="Only owners can edit.",
        content_hash="sha256:test",
    )

    result = await OpenAICompatibleKnowledgeModel().extract_topics(
        document_title="Requirements",
        source_units=(unit,),
    )

    settings = captured["settings"]
    assert isinstance(settings, LLMSettings)
    assert settings.model == "knowledge-model"
    assert settings.base_url == "https://models.example.test/v1"
    assert result.topics[0].source_unit_ids == ("DSU-1",)
    assert "TopicExtractionResult" in str(captured["prompt"])
