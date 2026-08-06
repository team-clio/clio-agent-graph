from pathlib import Path

import pytest

from clio_agent_graph.services.pcm.errors import PCMValidationError
from clio_agent_graph.services.pcm.models import IngestDocumentCommand
from clio_agent_graph.services.pcm.storage import MarkdownStore


@pytest.mark.asyncio
async def test_source_markdown_is_immutable_and_path_safe(tmp_path: Path) -> None:
    store = MarkdownStore(tmp_path)
    command = IngestDocumentCommand(
        event_id="EVENT-1",
        project_id="../../PROJECT-1",
        document_id="../requirements",
        revision="../../1",
        title="Requirements",
        markdown="# Rule\n\nOnly owners can edit.",
    )

    storage_path = await store.save_document_source(command)
    saved = await store.read(storage_path)

    assert Path(storage_path).is_absolute() is False
    assert ".." not in Path(storage_path).parts
    assert "Only owners can edit." in saved

    changed = command.model_copy(update={"markdown": "# Rule\n\nAnyone can edit."})
    with pytest.raises(PCMValidationError, match="different content"):
        await store.save_document_source(changed)


@pytest.mark.asyncio
async def test_storage_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(PCMValidationError, match="relative and contained"):
        await MarkdownStore(tmp_path).read("../secret")
