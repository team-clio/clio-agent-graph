"""Source와 Knowledge Markdown을 immutable 파일로 보존한다."""

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from clio_agent_graph.context.pcm.errors import PCMValidationError
from clio_agent_graph.context.pcm.models import (
    IngestDocumentCommand,
    KnowledgeDocument,
)


class DocumentSourceStore(Protocol):
    """Knowledge 생성에 사용한 정규화 원문을 보존하는 저장소 계약."""

    async def save_document_source(self, command: IngestDocumentCommand) -> str:
        """문서 원문을 저장하고 추후 추적 가능한 상대 경로를 반환한다."""

        ...


class MarkdownStore:
    """외부 식별자를 경로로 직접 사용하지 않는 immutable Markdown 저장소."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def save_document_source(self, command: IngestDocumentCommand) -> str:
        """입력 식별자를 안전한 경로로 바꿔 문서 원문을 불변 저장한다."""

        content_hash = _content_hash(command.markdown)
        relative_path = Path(
            "projects",
            _safe_id("project", command.project_id),
            "sources",
            "documents",
            _safe_id("document", command.document_id),
            f"{_safe_id('revision', command.revision)}.md",
        )
        content = _render_source(command, content_hash)
        await asyncio.to_thread(self._write_immutable, relative_path, content)
        return relative_path.as_posix()

    async def save_knowledge(self, document: KnowledgeDocument) -> str:
        """Knowledge revision과 provenance를 front matter가 있는 Markdown으로 저장한다."""

        relative_path = Path(
            "projects",
            _safe_id("project", document.project_id),
            "knowledge",
            document.knowledge_id,
            f"{document.knowledge_revision}.md",
        )
        content = _render_knowledge(document)
        await asyncio.to_thread(self._write_immutable, relative_path, content)
        return relative_path.as_posix()

    async def read(self, storage_path: str) -> str:
        """저장 루트 내부의 상대 경로만 허용해 Markdown 원문을 읽는다."""

        path = self._resolve_relative(storage_path)
        try:
            return await asyncio.to_thread(path.read_text, encoding="utf-8")
        except FileNotFoundError as exc:
            raise PCMValidationError(f"PCM Markdown is missing: {storage_path}") from exc

    def _write_immutable(self, relative_path: Path, content: str) -> None:
        destination = self._resolve_relative(relative_path.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode()
        if destination.exists():
            if destination.read_bytes() != encoded:
                raise PCMValidationError(
                    f"Immutable PCM Markdown already exists with different content: {relative_path}"
                )
            return
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _resolve_relative(self, storage_path: str) -> Path:
        relative = Path(storage_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise PCMValidationError("PCM storage path must be relative and contained.")
        resolved = (self._root / relative).resolve()
        if not resolved.is_relative_to(self._root):
            raise PCMValidationError("PCM storage path escapes the configured root.")
        return resolved


def _render_source(command: IngestDocumentCommand, content_hash: str) -> str:
    metadata = {
        "schema_version": 1,
        "source_type": "document",
        "project_id": command.project_id,
        "document_id": command.document_id,
        "source_revision": command.revision,
        "title": command.title,
        "content_hash": content_hash,
        "source_metadata": command.source_metadata,
    }
    return f"---\n{_front_matter(metadata)}---\n\n{command.markdown.strip()}\n"


def _render_knowledge(document: KnowledgeDocument) -> str:
    metadata = {
        "schema_version": 1,
        "project_id": document.project_id,
        "knowledge_id": document.knowledge_id,
        "logical_key": document.logical_key,
        "knowledge_type": document.knowledge_type,
        "title": document.title,
        "knowledge_revision": document.knowledge_revision,
        "pcm_revision": document.valid_from_pcm_revision,
        "is_tombstone": document.is_tombstone,
        "sources": [source.model_dump(mode="json") for source in document.sources],
        "related_knowledge_ids": list(document.related_knowledge_ids),
    }
    body = "" if document.is_tombstone else document.body_markdown.strip()
    return f"---\n{_front_matter(metadata)}---\n\n{body}\n"


def _front_matter(metadata: dict[str, object]) -> str:
    return "".join(
        f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}\n"
        for key, value in metadata.items()
    )


def _content_hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.strip().encode()).hexdigest()}"


def _safe_id(kind: str, value: str) -> str:
    return uuid5(NAMESPACE_URL, f"clio-pcm:{kind}:{value}").hex
