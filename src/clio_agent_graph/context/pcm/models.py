"""Project Context Memory의 인프라 독립적인 도메인 모델."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

KnowledgeType = Literal[
    "domain_rule",
    "requirement",
    "architecture",
    "component",
    "operation",
    "resolution",
]
SourceType = Literal["document", "repository", "resolved_issue"]
KnowledgeOperation = Literal["create", "update", "tombstone", "no_change"]


class PCMModel(BaseModel):
    """PCM 경계에서 추가 필드를 거부하는 공통 모델."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceReference(PCMModel):
    """Knowledge의 사실을 뒷받침하는 원본 위치."""

    source_type: SourceType
    source_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    locator: dict[str, object] = Field(default_factory=dict)
    content_hash: str | None = None


class DocumentSourceUnit(PCMModel):
    """정규화 Markdown을 heading 경계로 나눈 입력 단위."""

    source_unit_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    heading_path: tuple[str, ...] = ()
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class IngestDocumentCommand(PCMModel):
    """정규화 Markdown을 Knowledge로 반영하는 애플리케이션 명령."""

    event_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    source_metadata: dict[str, object] = Field(default_factory=dict)


class IngestRepositoryCommand(PCMModel):
    """고정 Git commit의 source code를 Knowledge로 반영하는 명령."""

    event_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")


class RepositorySourceUnit(PCMModel):
    """Repository 파일을 line 범위로 나눈 신뢰 가능한 입력 단위."""

    source_unit_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class ProjectContextSnapshot(PCMModel):
    """한 번의 분석이 끝까지 사용하는 PCM 및 Repository revision."""

    project_id: str = Field(min_length=1)
    pcm_revision: int = Field(ge=0)
    knowledge_index_revision: int = Field(ge=0)
    repository_revisions: dict[str, str] = Field(default_factory=dict)


class KnowledgeDocument(PCMModel):
    """특정 PCM 구간에서 유효한 하나의 Knowledge revision."""

    project_id: str = Field(min_length=1)
    knowledge_id: str = Field(min_length=1)
    logical_key: str = Field(min_length=1)
    knowledge_type: KnowledgeType
    title: str = Field(min_length=1)
    body_markdown: str
    knowledge_revision: int = Field(ge=1)
    valid_from_pcm_revision: int = Field(ge=1)
    valid_until_pcm_revision: int | None = Field(default=None, ge=1)
    sources: tuple[SourceReference, ...]
    related_knowledge_ids: tuple[str, ...] = ()
    is_tombstone: bool = False


class KnowledgeChange(PCMModel):
    """Knowledge Agent가 제안하고 PCM Service가 검증하는 단일 변경."""

    operation: KnowledgeOperation
    logical_key: str | None = None
    target_knowledge_id: str | None = None
    knowledge_type: KnowledgeType | None = None
    title: str | None = None
    body_markdown: str | None = None
    sources: tuple[SourceReference, ...] = ()
    related_knowledge_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_operation_contract(self) -> "KnowledgeChange":
        """연산별 필수·금지 필드를 함께 검사해 모호한 변경을 차단한다."""

        if self.operation == "create":
            if self.target_knowledge_id is not None:
                raise ValueError("create must not provide target_knowledge_id")
            if not self.logical_key:
                raise ValueError("create requires logical_key")
        else:
            if not self.target_knowledge_id:
                raise ValueError(f"{self.operation} requires target_knowledge_id")
            if self.logical_key is not None:
                raise ValueError(f"{self.operation} must not provide logical_key")

        if self.operation in {"create", "update"}:
            if not self.knowledge_type or not self.title or not self.body_markdown:
                raise ValueError(f"{self.operation} requires type, title, and body")
            if not self.sources:
                raise ValueError(f"{self.operation} requires at least one source")
        elif self.body_markdown is not None:
            raise ValueError(f"{self.operation} must not provide body_markdown")
        return self


class KnowledgeChangeSet(PCMModel):
    """하나의 source event에서 원자적으로 적용할 Knowledge 변경 묶음."""

    source_event_id: str = Field(min_length=1)
    base_pcm_revision: int = Field(ge=0)
    changes: tuple[KnowledgeChange, ...] = Field(min_length=1)


class KnowledgeCommitResult(PCMModel):
    """Knowledge commit의 공개 결과와 멱등성 정보."""

    commit_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    base_pcm_revision: int = Field(ge=0)
    pcm_revision: int = Field(ge=0)
    created_knowledge_ids: tuple[str, ...] = ()
    updated_knowledge_ids: tuple[str, ...] = ()
    tombstoned_knowledge_ids: tuple[str, ...] = ()
    unchanged_knowledge_ids: tuple[str, ...] = ()
    idempotent_replay: bool = False


class KnowledgeSearchRequest(PCMModel):
    """PCM Service 내부 검색 요청."""

    query: str = Field(min_length=1, max_length=1000)
    knowledge_types: tuple[KnowledgeType, ...] | None = None
    limit: int = Field(default=8, ge=1, le=20)


class KnowledgeSearchResult(PCMModel):
    """Knowledge 단위로 합쳐진 검색 결과."""

    knowledge_id: str
    knowledge_revision: int
    knowledge_type: KnowledgeType
    title: str
    matched_content: str
    score: float = Field(ge=0.0)
    sources: tuple[SourceReference, ...]


class KnowledgeSearchPage(PCMModel):
    """고정 snapshot에서 반환한 Knowledge 검색 결과."""

    project_id: str
    pcm_revision: int
    results: tuple[KnowledgeSearchResult, ...]
    vector_search_used: bool = False
    keyword_search_used: bool = True
    vector_index_stale: bool = False


class KnowledgeChunk(PCMModel):
    """검색 인덱스에 저장하는 heading-aware Knowledge 조각."""

    chunk_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    knowledge_id: str = Field(min_length=1)
    knowledge_revision: int = Field(ge=1)
    heading_path: tuple[str, ...] = ()
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    chunker_version: str = Field(min_length=1)
    valid_from_pcm_revision: int = Field(ge=1)


class ExtractedTopic(PCMModel):
    """Source Unit 묶음에서 Knowledge 후보로 추출한 임시 주제."""

    topic_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    knowledge_type: KnowledgeType
    summary: str = Field(min_length=1, max_length=2000)
    source_unit_ids: tuple[str, ...] = Field(min_length=1)
    suggested_search_queries: tuple[str, ...] = Field(min_length=1, max_length=5)


class TopicExtractionResult(PCMModel):
    """한 문서에서 추출한 중복 없는 Topic 목록."""

    topics: tuple[ExtractedTopic, ...] = Field(min_length=1)


class KnowledgeCandidate(PCMModel):
    """Topic과 통합할지 LLM이 비교하는 기존 Knowledge."""

    knowledge_id: str
    knowledge_revision: int = Field(ge=1)
    knowledge_type: KnowledgeType
    title: str
    body_markdown: str
    sources: tuple[SourceReference, ...]
    retrieval_reasons: tuple[str, ...] = ()


class KnowledgeChangeDraft(PCMModel):
    """LLM이 반환하는, 신뢰 가능한 Source Reference로 변환하기 전 변경안."""

    operation: Literal["create", "update", "no_change"]
    logical_key: str | None = None
    target_knowledge_id: str | None = None
    knowledge_type: KnowledgeType | None = None
    title: str | None = None
    body_markdown: str | None = None
    source_unit_ids: tuple[str, ...] = ()
    related_knowledge_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_operation_contract(self) -> "KnowledgeChangeDraft":
        """LLM 변경안이 create/update/no-change 의미를 일관되게 표현하게 한다."""

        if self.operation == "create":
            if not self.logical_key or self.target_knowledge_id is not None:
                raise ValueError("create requires only logical_key")
        else:
            if not self.target_knowledge_id or self.logical_key is not None:
                raise ValueError(f"{self.operation} requires only target_knowledge_id")

        if self.operation in {"create", "update"}:
            if not self.knowledge_type or not self.title or not self.body_markdown:
                raise ValueError(f"{self.operation} requires type, title, and body")
            if not self.source_unit_ids:
                raise ValueError(f"{self.operation} requires source_unit_ids")
        elif self.body_markdown is not None or self.source_unit_ids:
            raise ValueError("no_change must not provide body or source_unit_ids")
        return self


class KnowledgeChangeDraftSet(PCMModel):
    """Knowledge LLM의 structured output."""

    source_event_id: str = Field(min_length=1)
    base_pcm_revision: int = Field(ge=0)
    changes: tuple[KnowledgeChangeDraft, ...] = Field(min_length=1)
