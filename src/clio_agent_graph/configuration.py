"""루트 그래프 실행 설정과 독립 분석 그래프의 모델 backend 설정."""

import os
from dataclasses import dataclass, fields
from typing import Any

from langchain_core.runnables import RunnableConfig


@dataclass(kw_only=True)
class GraphConfig:
    """어시스턴트 단위 또는 실행 단위로 덮어쓸 수 있는 루트 그래프 설정값."""

    system_prompt: str = (
        "You are Clio, an engineering analysis agent. "
        "Turn a request into a small, verifiable execution plan."
    )
    max_steps: int = 5

    @classmethod
    def from_runnable_config(cls, config: RunnableConfig | None) -> "GraphConfig":
        configurable: dict[str, Any] = (config or {}).get("configurable", {})
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in configurable.items() if key in allowed})


class ModelBackendConfigurationError(RuntimeError):
    """지원하지 않는 chat backend가 설정됐을 때 발생한다."""


def load_chat_backend() -> str:
    """기존 LangChain API 경로와 Codex 구독 경로를 구분한다."""

    value = os.getenv("CLIO_CHAT_BACKEND", "langchain").strip().casefold()
    if value in {"langchain", "openai", "api"}:
        return "langchain"
    if value in {"codex", "codex-exec", "subscription"}:
        return "codex"
    raise ModelBackendConfigurationError(
        "CLIO_CHAT_BACKEND must be one of: langchain, openai, api, codex, codex-exec, subscription."
    )
