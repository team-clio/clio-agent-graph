"""교체 가능한 LLM 공급자와 LangChain Agent 실행기."""

import json
import os
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


@dataclass(frozen=True)
class LLMSettings:
    """환경 변수로 설정하는 OpenAI 호환 LLM 연결 정보."""

    provider: str
    model: str
    base_url: str
    api_key: str | None

    @classmethod
    def from_env(cls) -> "LLMSettings":
        provider = os.getenv("CLIO_LLM_PROVIDER", "deepseek")
        defaults = {
            "deepseek": ("deepseek-chat", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
            "openai_compatible": ("", "", ""),
        }
        if provider not in defaults:
            raise ValueError(f"Unsupported CLIO_LLM_PROVIDER: {provider}")
        default_model, default_base_url, default_key_env = defaults[provider]
        key_env = os.getenv("CLIO_LLM_API_KEY_ENV", default_key_env)
        return cls(
            provider=provider,
            model=os.getenv("CLIO_LLM_MODEL", default_model),
            base_url=os.getenv("CLIO_LLM_BASE_URL", default_base_url),
            api_key=os.getenv(key_env) if key_env else None,
        )

    @property
    def use_llm(self) -> bool:
        if not self.api_key:
            raise RuntimeError("LLM execution requires the configured API key.")
        return True


def build_chat_model(settings: LLMSettings):
    """선택된 OpenAI 호환 공급자의 LangChain ChatModel을 생성한다."""

    if not settings.model or not settings.base_url:
        raise RuntimeError("LLM mode requires CLIO_LLM_MODEL and CLIO_LLM_BASE_URL.")
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError('Install LLM support with: pip install -e ".[llm]"') from exc
    model_kwargs: dict[str, Any] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
    }
    if settings.provider == "deepseek":
        # LangChain's structured-output strategy sets tool_choice. DeepSeek rejects that
        # parameter in thinking mode, so Agent runs use its compatible non-thinking mode.
        model_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(**model_kwargs)


class ToolCallingAgent:
    """실제 LLM Tool-calling Agent를 실행한다."""

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

    def invoke(self, prompt: str) -> dict[str, Any]:
        settings = LLMSettings.from_env()
        _ = settings.use_llm
        agent = create_agent(
            model=build_chat_model(settings),
            tools=self.tools,
            system_prompt=(
                f"{self.system_prompt}\n\nWhen you are finished, return only one JSON object. "
                "Return field values, never a JSON Schema or an explanation. Required fields: "
                f"{', '.join(self.response_model.model_fields)}."
            ),
            name=self.name,
        )
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
        message = result["messages"][-1]
        if not isinstance(message, AIMessage) or not isinstance(message.content, str):
            raise RuntimeError("LLM Agent did not return a text final response.")
        return self.response_model.model_validate_json(_json_object(message.content)).model_dump()


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
