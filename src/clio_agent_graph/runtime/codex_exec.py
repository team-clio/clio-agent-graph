"""ChatGPT 구독으로 인증된 Codex CLI를 structured-output 모델처럼 사용한다."""

import json
import os
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class CodexExecError(RuntimeError):
    """Codex CLI 실행 자체가 완료되지 못했을 때 발생한다."""


class CodexExecOutputError(CodexExecError):
    """Codex 최종 응답이 요청한 Pydantic 계약과 다를 때 발생한다."""


class CodexExecStructuredInvoker:
    """`codex exec --output-schema`를 동기식 structured model 호출로 감싼다."""

    def __init__(
        self,
        *,
        command: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._command = command or os.getenv("CLIO_CODEX_COMMAND", "codex")
        self._model = model if model is not None else os.getenv("CLIO_CODEX_MODEL")
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.getenv("CLIO_CODEX_TIMEOUT_SECONDS", "180"))
        )
        if self._timeout_seconds <= 0:
            raise ValueError("Codex timeout must be greater than zero.")

    def invoke(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_type: type[ModelT],
        working_directory: str | Path | None = None,
    ) -> ModelT:
        """격리된 일회성 Codex run을 실행하고 최종 JSON만 검증해 반환한다."""

        with tempfile.TemporaryDirectory(prefix="clio-codex-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            schema_path = temporary_path / "output-schema.json"
            output_path = temporary_path / "last-message.json"
            schema_path.write_text(
                json.dumps(_strict_json_schema(output_type), ensure_ascii=False),
                encoding="utf-8",
            )

            execution_directory = (
                Path(working_directory).expanduser().resolve()
                if working_directory is not None
                else temporary_path
            )
            if not execution_directory.is_dir():
                raise CodexExecError(
                    f"Codex working directory does not exist: {execution_directory}"
                )

            command = [
                self._command,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ignore-user-config",
                "--ignore-rules",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--cd",
                str(execution_directory),
            ]
            if self._model is not None and self._model.strip():
                command.extend(["--model", self._model.strip()])
            command.append("-")

            child_environment = os.environ.copy()
            # 일반 API key가 설정돼 있어도 ChatGPT OAuth로 로그인한 Codex 자격 증명을 사용한다.
            child_environment.pop("OPENAI_API_KEY", None)
            prompt = _build_codex_prompt(system_prompt, user_prompt)
            try:
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=self._timeout_seconds,
                    check=False,
                    env=child_environment,
                )
            except FileNotFoundError as error:
                raise CodexExecError(f"Codex command was not found: {self._command}") from error
            except subprocess.TimeoutExpired as error:
                raise CodexExecError(
                    f"Codex exec exceeded {self._timeout_seconds:g} seconds."
                ) from error

            if completed.returncode != 0:
                details = _failure_details(completed)
                suffix = f" {details}" if details else ""
                raise CodexExecError(
                    f"Codex exec failed with exit code {completed.returncode}.{suffix}"
                )
            if not output_path.is_file():
                raise CodexExecOutputError("Codex exec did not create a final response file.")

            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                return output_type.model_validate(payload)
            except (json.JSONDecodeError, ValidationError) as error:
                raise CodexExecOutputError(str(error)) from error


def _build_codex_prompt(system_prompt: str, user_prompt: str) -> str:
    """도메인 system/user 의미를 Codex의 단일 비대화형 요청에 보존한다."""

    return "\n\n".join(
        (
            "Follow the domain instructions below exactly.",
            "[DOMAIN_SYSTEM_INSTRUCTIONS]",
            system_prompt,
            "[DOMAIN_REQUEST]",
            user_prompt,
            "Return only the final JSON object that satisfies the provided output schema.",
        )
    )


def _strict_json_schema(output_type: type[BaseModel]) -> dict:
    """Pydantic schema를 OpenAI structured-output의 strict object 규칙에 맞춘다."""

    schema = deepcopy(output_type.model_json_schema())
    return _make_schema_node_strict(schema)


def _make_schema_node_strict(node: dict) -> dict:
    """모든 object field를 required로 선언하고 추가 속성을 금지한다."""

    for definitions_key in ("$defs", "definitions"):
        definitions = node.get(definitions_key)
        if isinstance(definitions, dict):
            for definition in definitions.values():
                if isinstance(definition, dict):
                    _make_schema_node_strict(definition)

    if node.get("type") == "object":
        # Strict structured output은 자유 형식 dict를 지원하지 않는다. 그런 필드는
        # 빈 object로 제한하고 실제 반환값은 마지막에 Pydantic으로 다시 검증한다.
        node.pop("propertyNames", None)
        node["additionalProperties"] = False
        node.setdefault("properties", {})

    properties = node.get("properties")
    if isinstance(properties, dict):
        node["additionalProperties"] = False
        node["required"] = list(properties)
        for property_schema in properties.values():
            if isinstance(property_schema, dict):
                _make_schema_node_strict(property_schema)

    items = node.get("items")
    if isinstance(items, dict):
        _make_schema_node_strict(items)

    for union_key in ("anyOf", "oneOf", "allOf"):
        variants = node.get(union_key)
        if isinstance(variants, list):
            for variant in variants:
                if isinstance(variant, dict):
                    _make_schema_node_strict(variant)

    if node.get("default") is None:
        node.pop("default", None)
    return node


def _failure_details(completed: subprocess.CompletedProcess[str]) -> str:
    """인증 정보가 아닌 CLI 진단의 짧은 마지막 부분만 예외에 덧붙인다."""

    diagnostic = (completed.stderr or completed.stdout or "").strip()
    if not diagnostic:
        return ""
    tail = diagnostic[-2000:].replace("\x00", "")
    return f"Codex CLI diagnostic: {tail}"
