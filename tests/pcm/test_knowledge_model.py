import pytest
from langchain_core.messages import AIMessage

from clio_agent_graph.services.pcm import knowledge_model
from clio_agent_graph.services.pcm.knowledge_model import LangChainKnowledgeModel
from clio_agent_graph.services.pcm.models import DocumentSourceUnit


@pytest.mark.asyncio
async def test_knowledge_model_reuses_global_chat_model_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def fake_build_chat_model() -> FakeChatModel:
        captured["model_built"] = True
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

    result = await LangChainKnowledgeModel().extract_topics(
        document_title="Requirements",
        source_units=(unit,),
    )

    assert captured["model_built"] is True
    assert result.topics[0].source_unit_ids == ("DSU-1",)
    assert "TopicExtractionResult" in str(captured["prompt"])
