"""Quality Gate가 LLM 인용을 버리기 전에 식별자를 보완하고 진단 정보를 만든다."""

import re
from collections.abc import Iterable, Mapping
from typing import Any

_LOCATION_PATTERN = re.compile(r"^(?P<path>[^:]+?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?$")


def resolve_knowledge_reference(
    citation: Mapping[str, Any], document_evidence: Iterable[object]
) -> dict[str, Any] | None:
    """knowledge_id 없는 Knowledge 인용을 제공된 검색 결과의 출처 위치와 대조한다.

    출처 경로와 줄 범위가 겹치는 Knowledge가 정확히 하나일 때만 식별자를 반환한다. 여러 개면
    어느 Knowledge인지 추측하지 않는다.
    """

    location = _citation_location(citation)
    if location is None:
        return None
    path, start, end = location
    matches = {
        (document["knowledge_id"], document["knowledge_revision"])
        for document in document_evidence
        if isinstance(document, Mapping)
        and document.get("knowledge_id")
        and isinstance(document.get("knowledge_revision"), int)
        and any(
            _locator_matches(source.get("locator"), path, start, end)
            for source in document.get("sources", ())
            if isinstance(source, Mapping)
        )
    }
    if len(matches) != 1:
        return None
    knowledge_id, knowledge_revision = matches.pop()
    return {"knowledge_id": knowledge_id, "knowledge_revision": knowledge_revision}


def describe_citation(citation: Mapping[str, Any]) -> str:
    """버린 인용을 나중에 추적할 수 있게 위치와 채워진 식별 필드를 요약한다."""

    location = citation.get("location") or citation.get("file_path") or citation.get("source_id")
    fields = sorted(
        key
        for key in (
            "knowledge_id",
            "repository_id",
            "commit",
            "file_path",
            "start_line",
            "end_line",
        )
        if citation.get(key) not in (None, "")
    )
    return f"location={location or '-'}, fields={','.join(fields) or '-'}"


def _citation_location(citation: Mapping[str, Any]) -> tuple[str, int | None, int | None] | None:
    path = citation.get("file_path")
    if isinstance(path, str) and path:
        start = citation.get("start_line")
        end = citation.get("end_line")
        return (
            path,
            start if isinstance(start, int) else None,
            end if isinstance(end, int) else None,
        )
    location = citation.get("location")
    if not isinstance(location, str):
        return None
    match = _LOCATION_PATTERN.match(location.strip())
    if match is None:
        return None
    start = int(match["start"]) if match["start"] else None
    end = int(match["end"]) if match["end"] else start
    return match["path"], start, end


def _locator_matches(locator: object, path: str, start: int | None, end: int | None) -> bool:
    if not isinstance(locator, Mapping) or locator.get("path") != path:
        return False
    source_start = locator.get("start_line")
    source_end = locator.get("end_line")
    if start is None or not isinstance(source_start, int) or not isinstance(source_end, int):
        return True
    return start <= source_end and (end or start) >= source_start
