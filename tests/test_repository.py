import subprocess
from pathlib import Path

import pytest

from clio_agent_graph.services.pcm.models import ProjectContextSnapshot
from clio_agent_graph.services.repository import GitRepositoryService, RepositoryError
from clio_agent_graph.tools.repository import RepositoryToolFactory


@pytest.fixture(autouse=True)
def allow_local_repository_source(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Keep mirror-read tests local while HTTPS validation is covered separately."""

    if request.node.name in {
        "test_repository_registration_requires_https_source_uri",
        "test_repository_registration_rejects_embedded_credentials",
        "test_repository_register_rejects_non_https_source_uri",
    }:
        return
    monkeypatch.setattr(
        GitRepositoryService,
        "_validate_https_source_uri",
        staticmethod(lambda source_uri: None),
    )


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
        "list_repository_files",
        "search_repository_code",
        "read_repository_file",
    ]
    for repository_tool in tools:
        properties = repository_tool.args_schema.model_json_schema()["properties"]
        assert "project_id" not in properties
        assert "commit" not in properties

    result = await tools[2].ainvoke({"query": "can_edit"})
    assert result["results"][0]["commit"] == commit
    files = await tools[1].ainvoke({"repository_id": "backend", "limit": 1})
    assert files["files"] == [
        {"repository_id": "backend", "commit": commit, "path": "permissions.py"}
    ]


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


@pytest.mark.asyncio
async def test_repository_file_listing_is_snapshot_bound_and_hides_secret_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    first, _ = create_repository(source)
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
        repository_revisions={"backend": first},
    )

    files = await service.list_files(snapshot=snapshot)

    assert files == [{"repository_id": "backend", "commit": first, "path": "permissions.py"}]
    with pytest.raises(RepositoryError, match="between 1 and 200"):
        await service.list_files(snapshot=snapshot, limit=0)


@pytest.mark.asyncio
async def test_repository_removal_deletes_only_managed_mirror_and_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    create_repository(source)
    service = GitRepositoryService(tmp_path / "pcm-repositories")
    await service.register(
        project_id="PROJECT-1",
        repository_id="backend",
        source_uri=str(source),
        branch="main",
    )
    mirror = service._mirror_path("PROJECT-1", "backend")
    manifest = service._manifest_path("PROJECT-1", "backend")
    unrelated = service.root / "unrelated.txt"
    unrelated.write_text("preserve")

    assert await service.remove(project_id="PROJECT-1", repository_id="backend") is True
    assert not mirror.exists()
    assert not manifest.exists()
    assert unrelated.read_text() == "preserve"
    assert await service.remove(project_id="PROJECT-1", repository_id="backend") is False


@pytest.mark.asyncio
async def test_repository_removal_unlinks_managed_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    service = GitRepositoryService(tmp_path / "pcm-repositories")
    mirror = service._mirror_path("PROJECT-1", "backend")
    target = tmp_path / "unrelated-directory"
    target.mkdir()
    (target / "preserve.txt").write_text("preserve")
    mirror.parent.mkdir(parents=True)
    mirror.symlink_to(target, target_is_directory=True)

    assert await service.remove(project_id="PROJECT-1", repository_id="backend") is True
    assert not mirror.exists()
    assert (target / "preserve.txt").read_text() == "preserve"


def test_repository_registration_requires_https_source_uri(tmp_path: Path) -> None:
    service = GitRepositoryService(tmp_path / "pcm-repositories")

    with pytest.raises(RepositoryError, match="HTTPS"):
        service._validate_https_source_uri("git@github.com:clio/repository.git")
    with pytest.raises(RepositoryError, match="HTTPS"):
        service._validate_https_source_uri("/tmp/repository")
    service._validate_https_source_uri("https://github.com/clio/repository.git")


def test_repository_registration_rejects_embedded_credentials(tmp_path: Path) -> None:
    service = GitRepositoryService(tmp_path / "pcm-repositories")

    for source_uri in (
        "https://user@github.com/clio/repository.git",
        "https://user:token@github.com/clio/repository.git",
    ):
        with pytest.raises(RepositoryError, match="must not embed credentials"):
            service._validate_https_source_uri(source_uri)


@pytest.mark.asyncio
async def test_repository_register_rejects_non_https_source_uri(tmp_path: Path) -> None:
    service = GitRepositoryService(tmp_path / "pcm-repositories")

    with pytest.raises(RepositoryError, match="HTTPS"):
        await service.register(
            project_id="PROJECT-1",
            repository_id="backend",
            source_uri="http://git.example.internal/backend.git",
            branch="main",
        )
