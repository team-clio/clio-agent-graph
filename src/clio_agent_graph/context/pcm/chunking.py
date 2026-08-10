"""Knowledge Markdown을 heading과 문단 경계로 나누는 chunker."""

import hashlib
import re
from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from clio_agent_graph.context.pcm.models import KnowledgeChunk, KnowledgeDocument

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


class MarkdownKnowledgeChunker:
    """heading 의미를 유지하고 긴 section만 문단 경계에서 추가 분할한다."""

    version = "markdown-heading-v1"

    def __init__(self, max_characters: int = 1800) -> None:
        if max_characters < 256:
            raise ValueError("max_characters must be at least 256")
        self._max_characters = max_characters

    def chunk(self, document: KnowledgeDocument) -> tuple[KnowledgeChunk, ...]:
        if document.is_tombstone or not document.body_markdown.strip():
            return ()
        chunks: list[KnowledgeChunk] = []
        for heading_path, section in _sections(document.body_markdown):
            for ordinal, content in enumerate(_split_long_section(section, self._max_characters)):
                searchable_content = _searchable_content(
                    title=document.title,
                    heading_path=heading_path,
                    content=content,
                )
                content_hash = hashlib.sha256(searchable_content.encode()).hexdigest()
                identity = "\x1f".join(
                    (
                        document.knowledge_id,
                        str(document.knowledge_revision),
                        *heading_path,
                        str(ordinal),
                        content_hash,
                        self.version,
                    )
                )
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=f"chk_{uuid5(NAMESPACE_URL, identity).hex}",
                        project_id=document.project_id,
                        knowledge_id=document.knowledge_id,
                        knowledge_revision=document.knowledge_revision,
                        heading_path=heading_path,
                        content=searchable_content,
                        content_hash=f"sha256:{content_hash}",
                        chunker_version=self.version,
                        valid_from_pcm_revision=document.valid_from_pcm_revision,
                    )
                )
        return tuple(chunks)


def _sections(markdown: str) -> Sequence[tuple[tuple[str, ...], str]]:
    sections: list[tuple[tuple[str, ...], str]] = []
    headings: list[str] = []
    lines: list[str] = []
    in_fence = False
    fence_character = ""

    def flush() -> None:
        content = "\n".join(lines).strip()
        if content:
            sections.append((tuple(headings), content))
        lines.clear()

    for line in markdown.strip().splitlines():
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_character = marker[0]
            elif marker[0] == fence_character:
                in_fence = False
            lines.append(line)
            continue
        heading = None if in_fence else _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            headings[level - 1 :] = [heading.group(2).strip()]
            continue
        lines.append(line)
    flush()
    return sections or [((), markdown.strip())]


def _split_long_section(content: str, limit: int) -> tuple[str, ...]:
    if len(content) <= limit:
        return (content,)
    paragraphs = re.split(r"\n\s*\n", content)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = _hard_split(paragraph.strip(), limit)
        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if current and len(candidate) > limit:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return tuple(chunks)


def _hard_split(content: str, limit: int) -> tuple[str, ...]:
    if len(content) <= limit:
        return (content,)
    return tuple(content[index : index + limit] for index in range(0, len(content), limit))


def _searchable_content(*, title: str, heading_path: tuple[str, ...], content: str) -> str:
    context = " > ".join((title, *heading_path))
    return f"{context}\n\n{content}" if context else content
