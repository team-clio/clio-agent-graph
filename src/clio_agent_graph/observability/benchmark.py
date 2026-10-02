"""벤치마크 모드 설정과 영속 Tool 호출 로그 저장소."""

import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from pydantic_core import to_jsonable_python


def benchmark_mode_enabled() -> bool:
    value = os.getenv("CLIO_BENCHMARK_MODE", "false").strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("CLIO_BENCHMARK_MODE must be a boolean value.")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ToolCallLog(BaseModel):
    """벤치마크 결과로 전달하는 실제 Tool 실행 기록."""

    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    call_id: str
    parent_call_id: str | None = None
    tool: str
    operation: str | None = None
    started_at: str
    ended_at: str | None = None
    duration_seconds: float | None = None
    status: Literal["running", "success", "failure"] = "running"
    arguments: Any
    output: Any = None
    error: dict[str, str] | None = None


def payload(value: Any) -> Any:
    """JSON으로 변환할 수 없는 값은 타입과 표현을 명시한다."""
    return to_jsonable_python(
        value,
        fallback=lambda item: {
            "serialization": "repr",
            "type": type(item).__name__,
            "value": repr(item),
        },
    )


class ToolLogStore:
    """각 연산의 SQLite 연결로 thread·process 간 호출 기록을 공유한다."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tool_calls "
            "(sequence INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT UNIQUE, record TEXT)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS log_store (id INTEGER PRIMARY KEY, identity TEXT)"
        )
        connection.execute("INSERT OR IGNORE INTO log_store VALUES (1, ?)", (str(uuid4()),))
        connection.commit()
        return connection

    def boundary(self) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM tool_calls"
            ).fetchone()[0]
            identity = connection.execute("SELECT identity FROM log_store WHERE id = 1").fetchone()[
                0
            ]
        return {"sequence": sequence, "at": utc_now(), "store_id": identity}

    def start(self, record: ToolCallLog) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO tool_calls (call_id, record) VALUES (?, ?)",
                (record.call_id, record.model_dump_json()),
            )

    def finish(
        self, call_id: str, *, status: str, duration: float, output: Any, error: Any
    ) -> None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT record FROM tool_calls WHERE call_id = ?", (call_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Missing Tool start record: {call_id}")
            record = ToolCallLog.model_validate_json(row[0])
            updated = ToolCallLog.model_validate(
                {
                    **record.model_dump(),
                    "status": status,
                    "ended_at": utc_now(),
                    "duration_seconds": duration,
                    "output": payload(output),
                    "error": error,
                }
            )
            connection.execute(
                "UPDATE tool_calls SET record = ? WHERE call_id = ?",
                (updated.model_dump_json(), call_id),
            )

    def page(
        self, after: int, through: int, limit: int, store_id: str | None = None
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            identity = connection.execute("SELECT identity FROM log_store WHERE id = 1").fetchone()[
                0
            ]
            if store_id is not None and store_id != identity:
                raise ValueError("Tool log store was replaced")
            rows = connection.execute(
                "SELECT sequence, record FROM tool_calls "
                "WHERE sequence > ? AND sequence <= ? ORDER BY sequence LIMIT ?",
                (after, through, limit + 1),
            ).fetchall()
        items = rows[:limit]
        return {
            "items": [json.loads(row[1]) for row in items],
            "next_cursor": items[-1][0] if len(rows) > limit else None,
        }


def get_tool_log_store() -> ToolLogStore | None:
    if not benchmark_mode_enabled():
        return None
    return ToolLogStore(Path(os.getenv("CLIO_BENCHMARK_LOG_PATH", ".clio/benchmark-tools.sqlite3")))
