"""State contracts shared by graph nodes."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ClioState(TypedDict, total=False):
    """Persistent state for one Clio execution thread."""

    messages: Annotated[list[AnyMessage], add_messages]
    request: str
    plan: list[str]
    completed_steps: list[str]
    result: str
    error: str | None
