"""환경변수로 실제 모델 backend를 명시적으로 선택한다."""

import os


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
