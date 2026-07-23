"""그래프 노드가 공유하는 상태 계약."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ClioState(TypedDict, total=False):
    """한 번의 Clio 실행 동안 누적되는 상태 필드 집합."""

    # 메시지 리스트는 LangGraph의 add_messages 누산기로 병합된다.
    messages: Annotated[list[AnyMessage], add_messages]
    # normalize_request가 확정한 대표 사용자 요청 문자열.
    request: str
    # plan_request가 만든 순차 실행 계획.
    plan: list[str]
    # execute_plan이 처리 완료로 표시한 단계들.
    completed_steps: list[str]
    # 사용자에게 보여 줄 최종 요약 문자열.
    result: str
    # 실패를 상태에 남길 때 사용할 선택 필드.
    error: str | None
