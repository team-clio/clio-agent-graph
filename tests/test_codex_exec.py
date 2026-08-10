import json
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from clio_agent_graph.runtime.codex_exec import (
    CodexExecError,
    CodexExecOutputError,
    CodexExecStructuredInvoker,
)


class _Result(BaseModel):
    answer: str


class _DictionaryResult(BaseModel):
    metadata: dict[str, str]


def test_invoker_uses_read_only_ephemeral_codex_and_chatgpt_auth(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({"answer": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CodexExecStructuredInvoker(command="codex-test").invoke(
        system_prompt="system",
        user_prompt="user",
        output_type=_Result,
    )

    command = captured["command"]
    assert result.answer == "ok"
    assert command[:2] == ["codex-test", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert captured["input"].endswith(
        "Return only the final JSON object that satisfies the provided output schema."
    )
    assert "OPENAI_API_KEY" not in captured["env"]
    assert os.getenv("OPENAI_API_KEY") == "must-not-reach-codex"
    assert captured["schema"]["required"] == ["answer"]
    assert captured["schema"]["additionalProperties"] is False


def test_invoker_reports_nonzero_exit(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 17, stderr="schema is unsupported"
        ),
    )

    with pytest.raises(CodexExecError, match="schema is unsupported"):
        CodexExecStructuredInvoker().invoke(
            system_prompt="system",
            user_prompt="user",
            output_type=_Result,
        )


def test_invoker_rejects_invalid_structured_output(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("not-json", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CodexExecOutputError):
        CodexExecStructuredInvoker().invoke(
            system_prompt="system",
            user_prompt="user",
            output_type=_Result,
        )


def test_strict_schema_limits_free_form_dictionaries_to_empty_objects(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_run(command, **kwargs):
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text('{"metadata": {}}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CodexExecStructuredInvoker().invoke(
        system_prompt="system",
        user_prompt="user",
        output_type=_DictionaryResult,
    )

    metadata_schema = captured["schema"]["properties"]["metadata"]
    assert result.metadata == {}
    assert metadata_schema["properties"] == {}
    assert metadata_schema["required"] == []
    assert metadata_schema["additionalProperties"] is False
    assert "propertyNames" not in metadata_schema
