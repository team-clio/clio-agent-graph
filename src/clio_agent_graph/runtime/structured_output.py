"""Tool-calling 지원 provider가 공유하는 portable structured-output 정책."""

from typing import Any, TypeVar

from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel

StructuredResult = TypeVar("StructuredResult", bound=BaseModel)


def bind_structured_output(model: Any, schema: type[StructuredResult]) -> Any:
    """provider-native JSON Schema 대신 범용 function calling으로 schema를 강제한다."""

    return model.with_structured_output(schema, method="function_calling")


def tool_strategy(schema: type[StructuredResult]) -> ToolStrategy[StructuredResult]:
    """Agent 최종 응답도 provider-native API가 아닌 schema Tool 호출로 받는다."""

    return ToolStrategy(schema)
