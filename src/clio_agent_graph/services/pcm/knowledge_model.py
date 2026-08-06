"""기존 CLIO_LLM 설정을 사용하는 PCM Knowledge 모델."""

import json
from collections.abc import Mapping, Sequence
from typing import Protocol, TypeVar

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ValidationError

from clio_agent_graph.llm import LLMSettings, _json_object, build_chat_model
from clio_agent_graph.services.pcm.errors import KnowledgeModelOutputError
from clio_agent_graph.services.pcm.models import (
    DocumentSourceUnit,
    ExtractedTopic,
    KnowledgeCandidate,
    KnowledgeChangeDraftSet,
    ProjectContextSnapshot,
    RepositorySourceUnit,
    TopicExtractionResult,
)

StructuredResult = TypeVar("StructuredResult", bound=BaseModel)
KnowledgeSourceUnit = DocumentSourceUnit | RepositorySourceUnit


class KnowledgeModel(Protocol):
    """Source 분석과 Knowledge 변경 판단을 수행하는 LLM 경계."""

    async def extract_topics(
        self,
        *,
        document_title: str,
        source_units: Sequence[KnowledgeSourceUnit],
        validation_errors: Sequence[str] = (),
    ) -> TopicExtractionResult: ...

    async def generate_change_set(
        self,
        *,
        source_event_id: str,
        snapshot: ProjectContextSnapshot,
        topics: Sequence[ExtractedTopic],
        source_units: Sequence[KnowledgeSourceUnit],
        candidates: Mapping[str, Sequence[KnowledgeCandidate]],
        validation_errors: Sequence[str] = (),
    ) -> KnowledgeChangeDraftSet: ...


class OpenAICompatibleKnowledgeModel:
    """`.env`에서 주입된 기존 CLIO_LLM_* 설정을 재사용한다."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self._settings = settings

    async def extract_topics(
        self,
        *,
        document_title: str,
        source_units: Sequence[KnowledgeSourceUnit],
        validation_errors: Sequence[str] = (),
    ) -> TopicExtractionResult:
        payload = {
            "document_title": document_title,
            "source_units": [unit.model_dump(mode="json") for unit in source_units],
            "validation_errors_from_previous_attempt": list(validation_errors),
        }
        return await self._invoke_structured(
            task=(
                "Extract distinct, durable project-knowledge topics from the supplied source "
                "sections. Every topic must cite only supplied source_unit_ids. Prefer domain "
                "rules, requirements, architecture, components, operations, or resolutions."
            ),
            payload=payload,
            response_model=TopicExtractionResult,
        )

    async def generate_change_set(
        self,
        *,
        source_event_id: str,
        snapshot: ProjectContextSnapshot,
        topics: Sequence[ExtractedTopic],
        source_units: Sequence[KnowledgeSourceUnit],
        candidates: Mapping[str, Sequence[KnowledgeCandidate]],
        validation_errors: Sequence[str] = (),
    ) -> KnowledgeChangeDraftSet:
        payload = {
            "source_event_id": source_event_id,
            "base_pcm_revision": snapshot.pcm_revision,
            "topics": [topic.model_dump(mode="json") for topic in topics],
            "source_units": [unit.model_dump(mode="json") for unit in source_units],
            "candidates_by_topic": {
                key: [candidate.model_dump(mode="json") for candidate in values]
                for key, values in candidates.items()
            },
            "validation_errors_from_previous_attempt": list(validation_errors),
        }
        return await self._invoke_structured(
            task=(
                "Create one atomic Knowledge change set. Use create for a new durable topic, "
                "update only for a supplied candidate, and no_change when a candidate already "
                "contains the same knowledge. Cite only supplied source_unit_ids."
            ),
            payload=payload,
            response_model=KnowledgeChangeDraftSet,
        )

    async def _invoke_structured(
        self,
        *,
        task: str,
        payload: dict[str, object],
        response_model: type[StructuredResult],
    ) -> StructuredResult:
        settings = self._settings or LLMSettings.from_env()
        _ = settings.use_llm
        model = build_chat_model(settings)
        prompt = (
            "You are the knowledge synthesis component of Clio Project Context Memory. "
            "Do not invent sources or identifiers. Return only one JSON object matching this "
            f"JSON Schema:\n{json.dumps(response_model.model_json_schema())}\n\n"
            f"Task:\n{task}\n\nInput:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        response = await model.ainvoke(prompt)
        if not isinstance(response, AIMessage) or not isinstance(response.content, str):
            raise KnowledgeModelOutputError("Knowledge LLM did not return text output.")
        try:
            return response_model.model_validate_json(_json_object(response.content))
        except (ValidationError, ValueError) as exc:
            raise KnowledgeModelOutputError(f"Invalid Knowledge LLM output: {exc}") from exc
