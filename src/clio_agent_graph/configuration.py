"""Clio 그래프 런타임 설정."""

from dataclasses import dataclass, fields
from typing import Any

from langchain_core.runnables import RunnableConfig


@dataclass(kw_only=True)
class GraphConfig:
    """어시스턴트 단위 또는 실행 단위로 덮어쓸 수 있는 설정값."""

    # 기본 시스템 프롬프트는 현재 그래프가 어떤 역할을 하는지 짧게 설명한다.
    system_prompt: str = (
        "You are Clio, an engineering analysis agent. "
        "Turn a request into a small, verifiable execution plan."
    )
    # 계획은 너무 길어지지 않도록 상한을 둔다.
    max_steps: int = 5

    @classmethod
    def from_runnable_config(cls, config: RunnableConfig | None) -> "GraphConfig":
        # LangChain RunnableConfig 안의 configurable 섹션만 읽어 안전하게 매핑한다.
        configurable: dict[str, Any] = (config or {}).get("configurable", {})
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in configurable.items() if key in allowed})
