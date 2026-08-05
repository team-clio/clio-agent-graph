import subprocess
from pathlib import Path

import pytest

from clio_agent_graph.services.pcm.models import ProjectContextSnapshot
from clio_agent_graph.services.repository import GitRepositoryService, RepositoryError
from clio_agent_graph.tools.repository import RepositoryToolFactory


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
        'API_KEY="test-secret"\n\ndef can_edit(role: str) -> bool:\n    return role == "owner"\n'
    )
    (path / ".env").write_text("PASSWORD=never-expose\n")
    git(path, "add", ".")
    git(path, "commit", "-m", "initial")
    first = git(path, "rev-parse", "HEAD")
    (path / "permissions.py").write_text(
        "def can_edit(role: str) -> bool:\n    return role in {'owner', 'admin'}\n"
    )
    git(path, "add", "permissions.py")
    git(path, "commit", "-m", "allow admins")
    return first, git(path, "rev-parse", "HEAD")


@pytest.mark.asyncio
async def test_repository_reads_are_bound_to_snapshot_commit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    first, second = create_repository(source)
    service = GitRepositoryService(tmp_path / "pcm-repositories")
    registration = await service.register(
        project_id="PROJECT-1",
        repository_id="backend",
        source_uri=str(source),
        branch="main",
        commit=first,
    )
    old_snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
        repository_revisions={"backend": first},
    )

    await service.register(
        project_id="PROJECT-1",
        repository_id="backend",
        source_uri=str(source),
        branch="main",
        commit=second,
    )
    search = await service.search(snapshot=old_snapshot, query="role ==")
    file = await service.read_file(
        snapshot=old_snapshot,
        repository_id="backend",
        path="permissions.py",
        start_line=1,
        end_line=10,
    )

    assert registration.active_commit == first
    assert search[0].commit == first
    assert 'role == "owner"' in search[0].content
    assert file["commit"] == first
    assert "[REDACTED]" in file["content"]


@pytest.mark.asyncio
async def test_repository_tools_hide_project_and_commit_inputs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _, commit = create_repository(source)
    service = GitRepositoryService(tmp_path / "pcm-repositories")
    await service.register(
        project_id="PROJECT-1",
        repository_id="backend",
        source_uri=str(source),
        branch="main",
    )
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
        repository_revisions={"backend": commit},
    )
    tools = RepositoryToolFactory(service).create_tools(snapshot)

    assert [item.name for item in tools] == [
        "list_project_repositories",
        "search_repository_code",
        "read_repository_file",
    ]
    for repository_tool in tools:
        properties = repository_tool.args_schema.model_json_schema()["properties"]
        assert "project_id" not in properties
        assert "commit" not in properties

    result = await tools[1].ainvoke({"query": "can_edit"})
    assert result["results"][0]["commit"] == commit


@pytest.mark.asyncio
async def test_repository_file_access_blocks_escape_and_secret_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _, commit = create_repository(source)
    service = GitRepositoryService(tmp_path / "pcm-repositories")
    await service.register(
        project_id="PROJECT-1",
        repository_id="backend",
        source_uri=str(source),
        branch="main",
    )
    snapshot = ProjectContextSnapshot(
        project_id="PROJECT-1",
        pcm_revision=0,
        knowledge_index_revision=0,
        repository_revisions={"backend": commit},
    )

    with pytest.raises(RepositoryError, match="contained"):
        await service.read_file(snapshot=snapshot, repository_id="backend", path="../.env")
    with pytest.raises(RepositoryError, match="secret-bearing"):
        await service.read_file(snapshot=snapshot, repository_id="backend", path=".env")
