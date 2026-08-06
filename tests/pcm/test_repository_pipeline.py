import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from clio_agent_graph.services.pcm import InMemoryPCM
from clio_agent_graph.services.pcm.models import (
    ExtractedTopic,
    IngestRepositoryCommand,
    KnowledgeCandidate,
    KnowledgeChangeDraft,
    KnowledgeChangeDraftSet,
    ProjectContextSnapshot,
    RepositorySourceUnit,
    TopicExtractionResult,
)
from clio_agent_graph.services.pcm.repository_pipeline import RepositoryKnowledgePipeline
from clio_agent_graph.services.repository import GitRepositoryService


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def create_repository(path: Path) -> tuple[str, str]:
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Clio Test")
    git(path, "config", "user.email", "clio@example.test")
    (path / "permissions.py").write_text(
        'API_KEY="must-not-reach-model"\n\ndef can_edit(role):\n    return role == "owner"\n'
    )
    git(path, "add", ".")
    git(path, "commit", "-m", "initial")
    first = git(path, "rev-parse", "HEAD")
    (path / "permissions.py").write_text(
        "def can_edit(role):\n    return role in {'owner', 'admin'}\n"
    )
    git(path, "add", ".")
    git(path, "commit", "-m", "allow admin")
    return first, git(path, "rev-parse", "HEAD")


class FakeRepositoryKnowledgeModel:
    seen_units: Sequence[RepositorySourceUnit] = ()

    async def extract_topics(
        self,
        *,
        document_title: str,
        source_units: Sequence[RepositorySourceUnit],
        validation_errors: Sequence[str] = (),
    ) -> TopicExtractionResult:
        self.seen_units = source_units
        return TopicExtractionResult(
            topics=(
                ExtractedTopic(
                    topic_key="permissions-component",
                    title="Permissions component",
                    knowledge_type="component",
                    summary=document_title,
                    source_unit_ids=(source_units[0].source_unit_id,),
                    suggested_search_queries=("permissions component",),
                ),
            )
        )

    async def generate_change_set(
        self,
        *,
        source_event_id: str,
        snapshot: ProjectContextSnapshot,
        topics: Sequence[ExtractedTopic],
        source_units: Sequence[RepositorySourceUnit],
        candidates: Mapping[str, Sequence[KnowledgeCandidate]],
        validation_errors: Sequence[str] = (),
    ) -> KnowledgeChangeDraftSet:
        candidate = next(iter(candidates["permissions-component"]), None)
        common = {
            "knowledge_type": "component",
            "title": "Permissions component",
            "body_markdown": f"# Permissions component\n\n{source_units[0].content}",
            "source_unit_ids": (source_units[0].source_unit_id,),
            "reason": "The source code defines this component.",
        }
        change = (
            KnowledgeChangeDraft(
                operation="update",
                target_knowledge_id=candidate.knowledge_id,
                **common,
            )
            if candidate
            else KnowledgeChangeDraft(
                operation="create",
                logical_key="permissions-component",
                **common,
            )
        )
        return KnowledgeChangeDraftSet(
            source_event_id=source_event_id,
            base_pcm_revision=snapshot.pcm_revision,
            changes=(change,),
        )


@pytest.mark.asyncio
async def test_repository_pipeline_creates_and_updates_provenanced_knowledge(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    first, second = create_repository(source)
    repositories = GitRepositoryService(tmp_path / "repository-data")
    pcm = InMemoryPCM()
    model = FakeRepositoryKnowledgeModel()
    pipeline = RepositoryKnowledgePipeline(
        reader=pcm,
        writer=pcm,
        knowledge_model=model,  # type: ignore[arg-type]
        repositories=repositories,
    )
    await repositories.register(
        project_id="PROJECT-1",
        repository_id="backend",
        source_uri=str(source),
        branch="main",
        commit=first,
    )
    created = await pipeline.ingest(
        IngestRepositoryCommand(
            event_id="REPOSITORY-EVENT-1",
            project_id="PROJECT-1",
            repository_id="backend",
            commit=first,
        )
    )
    replay = await pipeline.ingest(
        IngestRepositoryCommand(
            event_id="REPOSITORY-EVENT-1",
            project_id="PROJECT-1",
            repository_id="backend",
            commit=first,
        )
    )

    assert created.pcm_revision == 1
    assert replay.idempotent_replay is True
    assert "must-not-reach-model" not in model.seen_units[0].content
    assert "[REDACTED]" in model.seen_units[0].content

    await repositories.register(
        project_id="PROJECT-1",
        repository_id="backend",
        source_uri=str(source),
        branch="main",
        commit=second,
    )
    updated = await pipeline.ingest(
        IngestRepositoryCommand(
            event_id="REPOSITORY-EVENT-2",
            project_id="PROJECT-1",
            repository_id="backend",
            commit=second,
        )
    )
    snapshot = await pcm.resolve_snapshot("PROJECT-1")
    document = await pcm.read_knowledge(
        snapshot=snapshot,
        knowledge_id=created.created_knowledge_ids[0],
    )

    assert updated.updated_knowledge_ids == created.created_knowledge_ids
    assert document.knowledge_revision == 2
    assert document.sources[0].source_type == "repository"
    assert document.sources[0].source_id == "backend"
    assert document.sources[0].source_revision == second
    assert document.sources[0].locator["path"] == "permissions.py"
