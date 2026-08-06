"""전역 LLM 선택과 LangChain Agent 실행기."""

import json
import os
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from clio_agent_graph.structured_output import tool_strategy

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)

DEFAULT_MODEL = "openai:gpt-4.1-mini"


@dataclass(frozen=True)
class LLMSettings:
    """모든 LLM 사용 지점이 공유하는 하나의 provider/model 설정."""

    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    extra_body: dict[str, Any] | None = None

    @classmethod
    def from_env(cls) -> "LLMSettings":
        """단일 ``CLIO_MODEL=provider:model`` 선택과 선택적 연결 옵션을 읽는다."""

        model = os.getenv("CLIO_MODEL", DEFAULT_MODEL).strip()
        if not model or ":" not in model:
            raise ValueError("CLIO_MODEL must use the 'provider:model' format.")

        api_key_env = os.getenv("CLIO_MODEL_API_KEY_ENV", "").strip() or None
        api_key = os.getenv(api_key_env) if api_key_env else None
        if api_key_env and not api_key:
            raise RuntimeError(f"LLM execution requires the API key in {api_key_env}.")

        extra_body_value = os.getenv("CLIO_MODEL_EXTRA_BODY", "").strip()
        extra_body: dict[str, Any] | None = None
        if extra_body_value:
            try:
                parsed_extra_body = json.loads(extra_body_value)
            except json.JSONDecodeError as exc:
                raise ValueError("CLIO_MODEL_EXTRA_BODY must be a JSON object.") from exc
            if not isinstance(parsed_extra_body, dict):
                raise ValueError("CLIO_MODEL_EXTRA_BODY must be a JSON object.")
            extra_body = parsed_extra_body

        return cls(
            model=model,
            base_url=os.getenv("CLIO_MODEL_BASE_URL", "").strip() or None,
            api_key_env=api_key_env,
            api_key=api_key,
            extra_body=extra_body,
        )

    @property
    def provider(self) -> str:
        """LangChain model identifier의 provider prefix."""

        return self.model.split(":", 1)[0]


def build_chat_model():
    """전역 선택을 LangChain provider integration에 위임해 ChatModel을 만든다."""

    selected = LLMSettings.from_env()
    model_kwargs: dict[str, Any] = {}
    if selected.base_url:
        model_kwargs["base_url"] = selected.base_url
    if selected.api_key:
        model_kwargs["api_key"] = selected.api_key
    if selected.extra_body:
        model_kwargs["extra_body"] = selected.extra_body
    return init_chat_model(selected.model, **model_kwargs)


class ToolCallingAgent:
    """전역으로 선택된 LLM을 사용하는 Tool-calling Agent."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        tools: list[BaseTool],
        response_model: type[StructuredOutput],
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools
        self.response_model = response_model

    def _create_agent(self):
        return create_agent(
            model=build_chat_model(),
            tools=self.tools,
            system_prompt=(
                f"{self.system_prompt}\n\nWhen you are finished, return only one JSON object. "
                "Return field values, never a JSON Schema or an explanation. Required fields: "
                f"{', '.join(self.response_model.model_fields)}. Follow this output schema: "
                f"{json.dumps(self.response_model.model_json_schema())}"
            ),
            response_format=tool_strategy(self.response_model),
            name=self.name,
        )

    def _parse_result(self, result: dict[str, Any]) -> dict[str, Any]:
        structured = result.get("structured_response")
        if structured is None:
            raise RuntimeError("LLM Agent did not return a structured response.")
        return self.response_model.model_validate(structured).model_dump()

    def invoke(self, prompt: str) -> dict[str, Any]:
        result = self._create_agent().invoke({"messages": [{"role": "user", "content": prompt}]})
        return self._parse_result(result)

    async def ainvoke(self, prompt: str) -> dict[str, Any]:
        """비동기 Graph Node에서 tool-calling loop를 실행한다."""

        result = await self._create_agent().ainvoke(
            {"messages": [{"role": "user", "content": prompt}]}
        )
        return self._parse_result(result)


def _json_object(content: str) -> str:
    """모델 응답에서 구조화 출력에 해당하는 JSON 객체만 추출한다."""

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return json.dumps(value)
    return stripped
