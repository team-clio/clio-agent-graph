"""Runtime configuration for the Clio graph."""

from dataclasses import dataclass, fields
from typing import Any

from langchain_core.runnables import RunnableConfig


@dataclass(kw_only=True)
class GraphConfig:
    """Values that may be overridden per assistant or per run."""

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
