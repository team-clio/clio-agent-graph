"""정규화 Markdown을 결정적인 Source Unit으로 변환한다."""

import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

from clio_agent_graph.services.pcm.errors import PCMValidationError
from clio_agent_graph.services.pcm.models import DocumentSourceUnit

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


class MarkdownSourceParser:
    """코드 fence를 보존하며 heading section별 Source Unit을 만든다."""

    def parse(
        self,
        *,
        document_id: str,
        revision: str,
        markdown: str,
    ) -> tuple[DocumentSourceUnit, ...]:
        if not document_id.strip() or not revision.strip():
            raise PCMValidationError("document_id and revision must not be blank.")
        normalized = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise PCMValidationError("Markdown document must not be blank.")

        sections: list[tuple[tuple[str, ...], str]] = []
        heading_stack: list[str] = []
        content: list[str] = []
        in_fence = False
        fence_character = ""

        def flush() -> None:
            body = "\n".join(content).strip()
            if body:
                sections.append((tuple(heading_stack), body))
            content.clear()

        for line in normalized.split("\n"):
            fence = _FENCE.match(line)
            if fence:
                marker = fence.group(1)
                if not in_fence:
                    in_fence = True
                    fence_character = marker[0]
                elif marker[0] == fence_character:
                    in_fence = False
                content.append(line)
                continue

            heading = None if in_fence else _HEADING.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                title = heading.group(2).strip()
                heading_stack[level - 1 :] = [title]
                continue
            content.append(line)
        flush()

        if not sections:
            raise PCMValidationError("Markdown document has no readable content.")
        return tuple(
            _source_unit(
                document_id=document_id,
                revision=revision,
                heading_path=heading_path,
                content=body,
                ordinal=ordinal,
            )
            for ordinal, (heading_path, body) in enumerate(sections)
        )


def _source_unit(
    *,
    document_id: str,
    revision: str,
    heading_path: tuple[str, ...],
    content: str,
    ordinal: int,
) -> DocumentSourceUnit:
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    identity = "\x1f".join((document_id, revision, *heading_path, str(ordinal), content_hash))
    return DocumentSourceUnit(
        source_unit_id=f"dsu_{uuid5(NAMESPACE_URL, identity).hex}",
        document_id=document_id,
        source_revision=revision,
        heading_path=heading_path,
        content=content,
        content_hash=f"sha256:{content_hash}",
    )
