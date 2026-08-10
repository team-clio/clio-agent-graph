"""Hybrid Issue Retrieval Agent를 실행하는 LangGraph subgraph."""

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from clio_agent_graph.workflows.reporting.matching.errors import (
    IssueRetrievalError,
    IssueRetrievalNotConfiguredError,
)
from clio_agent_graph.workflows.reporting.matching.models import (
    IssueCandidate,
    IssueRetrievalRequest,
    IssueRetrievalResponse,
)
from clio_agent_graph.workflows.reporting.normalization.models import NormalizedReport
from clio_agent_graph.workflows.reporting.retrieval.errors import RetrievalConfigurationError
from clio_agent_graph.workflows.reporting.retrieval.models import (
    BugSearchHit,
    BugSearchQuery,
    FusedBugHit,
    HydratedIssue,
    RetrievalScope,
    RetrievalSettings,
)
from clio_agent_graph.workflows.reporting.retrieval.ports import (
    EmbeddingModel,
    IssueRetrievalRepository,
)
from clio_agent_graph.workflows.reporting.retrieval.service import IssueRetrieverService

# 기존 RM 테스트와 외부 조립 코드가 작은 Fake callback을 계속 주입할 수 있게 보존한다.
IssueRetriever = Callable[[IssueRetrievalRequest], IssueRetrievalResponse | dict[str, Any]]


class IssueRetrievalInput(TypedDict):
    """상위 RM 그래프에서 Retrieval Agent로 들어오는 상태."""

    project_id: int
    bug_id: int
    normalized_report: NormalizedReport


class IssueRetrievalState(IssueRetrievalInput, total=False):
    """검색 fan-out과 Issue 집계 중 노드들이 공유하는 상태."""

    retrieval_request: IssueRetrievalRequest
    retrieval_query: BugSearchQuery
    query_embedding: list[float]
    embedding_model: str
    retrieval_scope: RetrievalScope
    exact_hits: list[BugSearchHit]
    lexical_hits: list[BugSearchHit]
    vector_hits: list[BugSearchHit]
    fused_bug_hits: list[FusedBugHit]
    hydrated_issues: list[HydratedIssue]
    issue_candidates: list[IssueCandidate]


class IssueRetrievalOutput(TypedDict):
    """Retrieval Agent가 상위 RM 그래프에 돌려주는 상태."""

    issue_candidates: list[IssueCandidate]


def build_issue_retrieval_subgraph(
    retriever: IssueRetriever | None = None,
    *,
    repository: IssueRetrievalRepository | None = None,
    embedding_model: EmbeddingModel | None = None,
    settings: RetrievalSettings | None = None,
):
    """Fake callback 또는 실제 Hybrid 검색 구성요소로 subgraph를 만든다."""

    if retriever is not None:
        return _build_callback_graph(retriever)

    actual_repository, actual_embedding_model = _load_default_dependencies(
        repository, embedding_model
    )
    service = IssueRetrieverService(
        actual_repository,
        actual_embedding_model,
        settings=settings,
    )

    def prepare_search(state: IssueRetrievalState) -> dict[str, Any]:
        """입력을 검증하고 query embedding과 검색 범위를 준비한다."""

        request = _request_from_state(state)
        try:
            query, embedding, model_name, scope = service.prepare(request)
        except RetrievalConfigurationError as error:
            raise IssueRetrievalNotConfiguredError(str(error)) from error
        return {
            "retrieval_request": request,
            "retrieval_query": query,
            "query_embedding": embedding,
            "embedding_model": model_name,
            "retrieval_scope": scope,
        }

    def search_exact(state: IssueRetrievalState) -> dict[str, Any]:
        """정확 오류 신호 검색을 실행한다."""

        return {
            "exact_hits": service.search_exact(state["retrieval_query"], state["retrieval_scope"])
        }

    def search_lexical(state: IssueRetrievalState) -> dict[str, Any]:
        """Trigram 문자열 검색을 실행한다."""

        return {
            "lexical_hits": service.search_lexical(
                state["retrieval_query"], state["retrieval_scope"]
            )
        }

    def search_vector(state: IssueRetrievalState) -> dict[str, Any]:
        """Vector 의미 검색을 실행한다."""

        return {
            "vector_hits": service.search_vector(
                state["retrieval_query"],
                state["retrieval_scope"],
                state["query_embedding"],
                state["embedding_model"],
            )
        }

    def fuse_hits(state: IssueRetrievalState) -> dict[str, Any]:
        """세 채널 결과를 하나의 Bug 순위로 합친다."""

        return {
            "fused_bug_hits": service.fuse(
                [*state["exact_hits"], *state["lexical_hits"], *state["vector_hits"]]
            )
        }

    def hydrate_issues(state: IssueRetrievalState) -> dict[str, Any]:
        """상위 Bug가 연결된 Issue와 snapshot을 읽는다."""

        return {
            "hydrated_issues": service.hydrate(state["retrieval_request"], state["fused_bug_hits"])
        }

    def rank_issues(state: IssueRetrievalState) -> dict[str, Any]:
        """Issue별 점수를 계산해 RM 후보 상한을 적용한다."""

        return {
            "issue_candidates": service.aggregate(state["fused_bug_hits"], state["hydrated_issues"])
        }

    builder = StateGraph(
        IssueRetrievalState,
        input_schema=IssueRetrievalInput,
        output_schema=IssueRetrievalOutput,
    )
    builder.add_node("prepare_search", prepare_search)
    builder.add_node("search_exact", search_exact)
    builder.add_node("search_lexical", search_lexical)
    builder.add_node("search_vector", search_vector)
    builder.add_node("fuse_bug_hits", fuse_hits)
    builder.add_node("hydrate_issues", hydrate_issues)
    builder.add_node("rank_and_limit", rank_issues)
    builder.add_edge(START, "prepare_search")
    builder.add_edge("prepare_search", "search_exact")
    builder.add_edge("prepare_search", "search_lexical")
    builder.add_edge("prepare_search", "search_vector")
    # 노드 이름 list를 시작점으로 주면 세 검색이 모두 끝난 뒤 한 번만 다음 노드가 실행된다.
    builder.add_edge(["search_exact", "search_lexical", "search_vector"], "fuse_bug_hits")
    builder.add_edge("fuse_bug_hits", "hydrate_issues")
    builder.add_edge("hydrate_issues", "rank_and_limit")
    builder.add_edge("rank_and_limit", END)
    return builder.compile()


def _build_callback_graph(retriever: IssueRetriever):
    """기존 Fake callback을 위한 작은 호환 graph를 만든다."""

    def retrieve_issue_candidates(state: IssueRetrievalState) -> dict[str, Any]:
        request = _request_from_state(state)
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                response = IssueRetrievalResponse.model_validate(retriever(request))
                return {"issue_candidates": response.candidates}
            except IssueRetrievalNotConfiguredError:
                raise
            except Exception as error:
                last_error = error
        raise IssueRetrievalError("Issue retrieval failed after one retry.") from last_error

    builder = StateGraph(
        IssueRetrievalState,
        input_schema=IssueRetrievalInput,
        output_schema=IssueRetrievalOutput,
    )
    builder.add_node("retrieve_issue_candidates", retrieve_issue_candidates)
    builder.add_edge(START, "retrieve_issue_candidates")
    builder.add_edge("retrieve_issue_candidates", END)
    return builder.compile()


def _request_from_state(state: IssueRetrievalState) -> IssueRetrievalRequest:
    """상위 state의 필요한 필드만 공개 요청 계약으로 검증한다."""

    return IssueRetrievalRequest.model_validate(
        {
            "project_id": state["project_id"],
            "bug_id": state["bug_id"],
            "normalized_report": state["normalized_report"],
        }
    )


def _load_default_dependencies(
    repository: IssueRetrievalRepository | None,
    embedding_model: EmbeddingModel | None,
) -> tuple[IssueRetrievalRepository, EmbeddingModel]:
    """운영 adapter import와 객체 생성을 graph 실행 전까지 가볍게 유지한다."""

    if repository is None:
        from clio_agent_graph.workflows.reporting.retrieval.postgres import (
            PostgresRetrievalRepository,
        )

        repository = PostgresRetrievalRepository()
    if embedding_model is None:
        from clio_agent_graph.workflows.reporting.retrieval.embedding_factory import (
            load_default_embedding_model,
        )

        embedding_model = load_default_embedding_model()
    return repository, embedding_model
