"""전역으로 선택된 LangChain 모델을 사용하는 PCM Knowledge 모델."""

import json
from collections.abc import Mapping, Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from clio_agent_graph.context.pcm.errors import KnowledgeModelOutputError
from clio_agent_graph.context.pcm.models import (
    DocumentSourceUnit,
    ExtractedTopic,
    KnowledgeCandidate,
    KnowledgeChangeDraftSet,
    ProjectContextSnapshot,
    RepositorySourceUnit,
    TopicExtractionResult,
)
from clio_agent_graph.runtime.llm import build_chat_model
from clio_agent_graph.runtime.structured_output import bind_structured_output

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
    ) -> TopicExtractionResult:
        """원문 단위에서 장기간 재사용할 주제와 근거 ID를 추출한다."""

        ...

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
        """추출 주제와 기존 후보를 비교해 create/update/no-change 변경안을 만든다."""

        ...


class LangChainKnowledgeModel:
    """다른 모든 Agent와 같은 ``CLIO_MODEL`` 선택을 재사용한다."""

    async def extract_topics(
        self,
        *,
        document_title: str,
        source_units: Sequence[KnowledgeSourceUnit],
        validation_errors: Sequence[str] = (),
    ) -> TopicExtractionResult:
        """Source Unit만 근거로 사용할 수 있는 주제 추출 요청을 실행한다."""

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
        """현재 snapshot의 후보 안에서만 갱신 대상을 고르는 변경안을 생성한다."""

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
        model = bind_structured_output(build_chat_model(), response_model)
        prompt = (
            "You are the knowledge synthesis component of Clio Project Context Memory. "
            "Do not invent sources or identifiers. Return only one JSON object matching this "
            f"JSON Schema:\n{json.dumps(response_model.model_json_schema())}\n\n"
            f"Task:\n{task}\n\nInput:\n{json.dumps(payload, ensure_ascii=False)}"
        )
        response = await model.ainvoke(prompt)
        try:
            return response_model.model_validate(response)
        except (ValidationError, ValueError) as exc:
            raise KnowledgeModelOutputError(f"Invalid Knowledge LLM output: {exc}") from exc


# 이전 공개 이름은 호출부 호환을 위해 남기되 별도 provider 설정은 받지 않는다.
OpenAICompatibleKnowledgeModel = LangChainKnowledgeModel
