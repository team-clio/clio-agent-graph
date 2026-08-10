"""Commit-addressed on-premise Git repository mirror와 읽기 서비스."""

import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from clio_agent_graph.context.pcm.models import ProjectContextSnapshot, RepositorySourceUnit

_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_DENIED_FILE_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "credentials",
    "id_rsa",
    "id_ed25519",
}
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|password|passwd|secret|token|authorization)(\s*[:=]\s*)([^\s]+)"
)
_SOURCE_EXTENSIONS = {
    ".c",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".php",
    ".proto",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}


class RepositoryError(RuntimeError):
    """Repository 등록 또는 snapshot 읽기 계약 위반."""


class RepositoryRegistration(BaseModel):
    """프로젝트에 등록되어 현재 활성화된 repository revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    repository_id: str
    branch: str
    active_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    file_count: int = Field(ge=0)


class RepositorySearchHit(BaseModel):
    """고정 commit에서 발견한 한 줄의 코드 근거."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: str
    commit: str
    path: str
    line: int = Field(ge=1)
    content: str


@dataclass(frozen=True)
class GitRepositoryService:
    """로컬 bare mirror를 관리하고 snapshot-bound 코드 탐색을 제공한다."""

    root: Path

    @classmethod
    def from_data_root(cls, data_root: Path) -> "GitRepositoryService":
        return cls(root=data_root / "repositories")

    async def register(
        self,
        *,
        project_id: str,
        repository_id: str,
        source_uri: str,
        branch: str,
        commit: str | None = None,
    ) -> RepositoryRegistration:
        return await asyncio.to_thread(
            self._register, project_id, repository_id, source_uri, branch, commit
        )

    def _register(
        self,
        project_id: str,
        repository_id: str,
        source_uri: str,
        branch: str,
        commit: str | None,
    ) -> RepositoryRegistration:
        self._validate_https_source_uri(source_uri)
        mirror = self._mirror_path(project_id, repository_id)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        if mirror.exists():
            self._git(mirror, "remote", "set-url", "origin", source_uri)
            self._git(mirror, "fetch", "--prune", "origin", "+refs/heads/*:refs/heads/*")
        else:
            self._run("git", "clone", "--mirror", "--", source_uri, str(mirror))
        revision = self._resolve_commit(mirror, commit or f"refs/heads/{branch}")
        file_count = len(self._git(mirror, "ls-tree", "-r", "--name-only", revision).splitlines())
        registration = RepositoryRegistration(
            project_id=project_id,
            repository_id=repository_id,
            branch=branch,
            active_commit=revision,
            file_count=file_count,
        )
        self._write_manifest(registration)
        return registration

    async def remove(self, *, project_id: str, repository_id: str) -> bool:
        """Idempotently delete this repository's server-managed mirror and manifest."""

        return await asyncio.to_thread(self._remove, project_id, repository_id)

    def _remove(self, project_id: str, repository_id: str) -> bool:
        mirror = self._mirror_path(project_id, repository_id)
        manifest = self._manifest_path(project_id, repository_id)
        removed = False
        for path in (mirror, manifest):
            if not path.exists() and not path.is_symlink():
                continue
            self._assert_managed_path(path, project_id, repository_id)
            if path.is_symlink() or not path.is_dir():
                path.unlink()
            else:
                shutil.rmtree(path)
            removed = True
        return removed

    async def activate_revision(
        self,
        *,
        project_id: str,
        repository_id: str,
        branch: str,
        after_commit: str,
    ) -> RepositoryRegistration:
        return await asyncio.to_thread(
            self._activate_revision, project_id, repository_id, branch, after_commit
        )

    async def changed_paths(
        self,
        *,
        project_id: str,
        repository_id: str,
        before_commit: str,
        after_commit: str,
    ) -> list[str]:
        if not _COMMIT_PATTERN.fullmatch(before_commit) or not _COMMIT_PATTERN.fullmatch(
            after_commit
        ):
            raise RepositoryError("diff revisions must be full Git commit SHAs")
        mirror = self._mirror_path(project_id, repository_id)
        output = await asyncio.to_thread(
            self._git,
            mirror,
            "diff",
            "--name-only",
            self._resolve_commit(mirror, before_commit),
            self._resolve_commit(mirror, after_commit),
            "--",
        )
        return [path for path in output.splitlines() if not self._denied_path(path)]

    def _activate_revision(
        self, project_id: str, repository_id: str, branch: str, after_commit: str
    ) -> RepositoryRegistration:
        if not _COMMIT_PATTERN.fullmatch(after_commit):
            raise RepositoryError("after_commit must be a full Git commit SHA")
        current = self._read_manifest(project_id, repository_id)
        mirror = self._mirror_path(project_id, repository_id)
        self._git(mirror, "fetch", "--prune", "origin", "+refs/heads/*:refs/heads/*")
        revision = self._resolve_commit(mirror, after_commit)
        branch_head = self._resolve_commit(mirror, f"refs/heads/{branch}")
        if revision != branch_head:
            raise RepositoryError("after_commit is not the current configured branch head")
        file_count = len(self._git(mirror, "ls-tree", "-r", "--name-only", revision).splitlines())
        updated = current.model_copy(
            update={"branch": branch, "active_commit": revision, "file_count": file_count}
        )
        self._write_manifest(updated)
        return updated

    async def list_revisions(self, project_id: str) -> dict[str, str]:
        return await asyncio.to_thread(self._list_revisions, project_id)

    def _list_revisions(self, project_id: str) -> dict[str, str]:
        directory = self._project_path(project_id) / "manifests"
        if not directory.exists():
            return {}
        registrations = [
            RepositoryRegistration.model_validate_json(path.read_text())
            for path in directory.glob("*.json")
        ]
        return {item.repository_id: item.active_commit for item in registrations}

    async def list_repositories(
        self, snapshot: ProjectContextSnapshot
    ) -> list[RepositoryRegistration]:
        registrations = []
        for repository_id, commit in snapshot.repository_revisions.items():
            registration = await asyncio.to_thread(
                self._read_manifest, snapshot.project_id, repository_id
            )
            registrations.append(registration.model_copy(update={"active_commit": commit}))
        return registrations

    async def collect_source_units(
        self,
        *,
        project_id: str,
        repository_id: str,
        commit: str,
        max_files: int = 30,
        max_total_bytes: int = 120_000,
        max_units: int = 60,
    ) -> tuple[RepositorySourceUnit, ...]:
        """고정 commit의 주요 tracked text source를 bounded line 단위로 수집한다."""

        return await asyncio.to_thread(
            self._collect_source_units,
            project_id,
            repository_id,
            commit,
            max_files,
            max_total_bytes,
            max_units,
        )

    def _collect_source_units(
        self,
        project_id: str,
        repository_id: str,
        commit: str,
        max_files: int,
        max_total_bytes: int,
        max_units: int,
    ) -> tuple[RepositorySourceUnit, ...]:
        if min(max_files, max_total_bytes, max_units) < 1:
            raise RepositoryError("repository source collection limits must be positive")
        mirror = self._mirror_path(project_id, repository_id)
        revision = self._resolve_commit(mirror, commit)
        listing = self._git(mirror, "ls-tree", "-r", "-l", revision)
        candidates: list[tuple[str, int]] = []
        for entry in listing.splitlines():
            metadata, separator, path = entry.partition("\t")
            if not separator or self._denied_path(path):
                continue
            parts = metadata.split()
            if len(parts) != 4 or parts[1] != "blob" or not parts[3].isdigit():
                continue
            size = int(parts[3])
            if size == 0 or size > 64_000 or not self._source_path(path):
                continue
            candidates.append((path, size))
        candidates.sort(key=lambda item: (self._source_priority(item[0]), item[0]))

        units: list[RepositorySourceUnit] = []
        total_bytes = 0
        for path, size in candidates[:max_files]:
            if total_bytes + size > max_total_bytes:
                continue
            content = self._git(mirror, "show", f"{revision}:{path}")
            total_bytes += len(content.encode(errors="replace"))
            for start_line, end_line, chunk in self._code_chunks(content):
                chunk = self._mask_secrets(chunk)
                digest = sha256(chunk.encode()).hexdigest()
                units.append(
                    RepositorySourceUnit(
                        source_unit_id=(
                            f"repo:{sha256(repository_id.encode()).hexdigest()[:12]}:"
                            f"{revision[:12]}:{sha256(path.encode()).hexdigest()[:12]}:"
                            f"{start_line}-{end_line}:{digest[:12]}"
                        ),
                        repository_id=repository_id,
                        commit=revision,
                        path=path,
                        start_line=start_line,
                        end_line=end_line,
                        content=chunk,
                        content_hash=f"sha256:{digest}",
                    )
                )
                if len(units) >= max_units:
                    return tuple(units)
        if not units:
            raise RepositoryError("repository contains no eligible text source files")
        return tuple(units)

    async def search(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        query: str,
        repository_id: str | None = None,
        limit: int = 20,
    ) -> list[RepositorySearchHit]:
        if not query.strip():
            raise RepositoryError("code search query must contain searchable text")
        if not 1 <= limit <= 50:
            raise RepositoryError("code search limit must be between 1 and 50")
        targets = self._snapshot_targets(snapshot, repository_id)
        hits: list[RepositorySearchHit] = []
        for target_id, commit in targets:
            output = await asyncio.to_thread(
                self._git_allow_no_match,
                self._mirror_path(snapshot.project_id, target_id),
                "grep",
                "-n",
                "-I",
                "-i",
                "-e",
                query,
                commit,
                "--",
            )
            for line in output.splitlines():
                match = re.match(rf"^{re.escape(commit)}:(.*?):(\d+):(.*)$", line)
                if not match:
                    continue
                path, line_number, matched = match.groups()
                if self._denied_path(path):
                    continue
                hits.append(
                    RepositorySearchHit(
                        repository_id=target_id,
                        commit=commit,
                        path=path,
                        line=int(line_number),
                        content=self._mask_secrets(matched)[:500],
                    )
                )
                if len(hits) >= limit:
                    return hits
        return hits

    async def list_files(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        repository_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, str]]:
        """List eligible tracked files at the snapshot-bound commit."""

        if not 1 <= limit <= 200:
            raise RepositoryError("repository file list limit must be between 1 and 200")
        files: list[dict[str, str]] = []
        for target_id, commit in self._snapshot_targets(snapshot, repository_id):
            output = await asyncio.to_thread(
                self._git,
                self._mirror_path(snapshot.project_id, target_id),
                "ls-tree",
                "-r",
                "--name-only",
                commit,
            )
            for path in output.splitlines():
                normalized = self._safe_relative_path(path)
                if self._denied_path(normalized):
                    continue
                files.append({"repository_id": target_id, "commit": commit, "path": normalized})
                if len(files) >= limit:
                    return files
        return files

    async def read_file(
        self,
        *,
        snapshot: ProjectContextSnapshot,
        repository_id: str,
        path: str,
        start_line: int = 1,
        end_line: int = 200,
    ) -> dict[str, object]:
        commit = self._snapshot_commit(snapshot, repository_id)
        normalized = self._safe_relative_path(path)
        if self._denied_path(normalized):
            raise RepositoryError("access to secret-bearing files is denied")
        if start_line < 1 or end_line < start_line or end_line - start_line + 1 > 400:
            raise RepositoryError("line range must contain between 1 and 400 lines")
        content = await asyncio.to_thread(
            self._git,
            self._mirror_path(snapshot.project_id, repository_id),
            "show",
            f"{commit}:{normalized}",
        )
        lines = content.splitlines()
        selected = lines[start_line - 1 : end_line]
        return {
            "repository_id": repository_id,
            "commit": commit,
            "path": normalized,
            "start_line": start_line,
            "end_line": min(end_line, len(lines)),
            "content": "\n".join(
                f"{number}: {self._mask_secrets(line)}"
                for number, line in enumerate(selected, start=start_line)
            ),
            "truncated": end_line < len(lines),
        }

    def _snapshot_targets(
        self, snapshot: ProjectContextSnapshot, repository_id: str | None
    ) -> list[tuple[str, str]]:
        if repository_id:
            return [(repository_id, self._snapshot_commit(snapshot, repository_id))]
        return sorted(snapshot.repository_revisions.items())

    @staticmethod
    def _snapshot_commit(snapshot: ProjectContextSnapshot, repository_id: str) -> str:
        try:
            return snapshot.repository_revisions[repository_id]
        except KeyError as exc:
            raise RepositoryError("repository is not available in the bound snapshot") from exc

    @staticmethod
    def _validate_https_source_uri(source_uri: str) -> None:
        parsed = urlparse(source_uri)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RepositoryError("repository source_uri must be an HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise RepositoryError("repository source_uri must not embed credentials")

    def _assert_managed_path(self, path: Path, project_id: str, repository_id: str) -> None:
        expected = {
            self._mirror_path(project_id, repository_id),
            self._manifest_path(project_id, repository_id),
        }
        if path not in expected or self.root not in path.parents:
            raise RepositoryError("refusing to delete a path outside the managed repository store")

    def _project_path(self, project_id: str) -> Path:
        return self.root / sha256(project_id.encode()).hexdigest()

    def _mirror_path(self, project_id: str, repository_id: str) -> Path:
        return (
            self._project_path(project_id)
            / "mirrors"
            / (sha256(repository_id.encode()).hexdigest() + ".git")
        )

    def _manifest_path(self, project_id: str, repository_id: str) -> Path:
        return (
            self._project_path(project_id)
            / "manifests"
            / (sha256(repository_id.encode()).hexdigest() + ".json")
        )

    def _read_manifest(self, project_id: str, repository_id: str) -> RepositoryRegistration:
        path = self._manifest_path(project_id, repository_id)
        if not path.exists():
            raise RepositoryError("repository is not registered for this project")
        registration = RepositoryRegistration.model_validate_json(path.read_text())
        if registration.repository_id != repository_id:
            raise RepositoryError("repository manifest identity mismatch")
        return registration

    def _write_manifest(self, registration: RepositoryRegistration) -> None:
        path = self._manifest_path(registration.project_id, registration.repository_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", dir=path.parent, delete=False) as temporary:
            temporary.write(registration.model_dump_json())
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)

    @staticmethod
    def _safe_relative_path(path: str) -> str:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
            raise RepositoryError("repository path must be a contained relative path")
        return candidate.as_posix()

    @staticmethod
    def _denied_path(path: str) -> bool:
        candidate = PurePosixPath(path)
        return candidate.name.lower() in _DENIED_FILE_NAMES or any(
            part.lower() in {".git", ".ssh"} for part in candidate.parts
        )

    @staticmethod
    def _mask_secrets(content: str) -> str:
        return _SECRET_PATTERN.sub(r"\1\2[REDACTED]", content)

    @staticmethod
    def _source_path(path: str) -> bool:
        candidate = PurePosixPath(path)
        return candidate.suffix.lower() in _SOURCE_EXTENSIONS or candidate.name.lower() in {
            "dockerfile",
            "makefile",
        }

    @staticmethod
    def _source_priority(path: str) -> tuple[int, int]:
        candidate = PurePosixPath(path)
        lowered = path.lower()
        generated = any(
            part in {"vendor", "dist", "build", "node_modules"} for part in candidate.parts
        )
        tests = "test" in lowered
        documentation = candidate.suffix.lower() == ".md"
        return (3 if generated else 2 if tests else 1 if documentation else 0, len(candidate.parts))

    @staticmethod
    def _code_chunks(content: str) -> list[tuple[int, int, str]]:
        lines = content.splitlines()
        chunks: list[tuple[int, int, str]] = []
        start = 0
        while start < len(lines):
            end = min(start + 120, len(lines))
            while end > start + 1 and len("\n".join(lines[start:end])) > 8_000:
                end -= 1
            chunk = "\n".join(lines[start:end]).strip()
            if chunk:
                chunks.append((start + 1, end, chunk[:8_000]))
            start = end
        return chunks

    def _resolve_commit(self, mirror: Path, revision: str) -> str:
        resolved = self._git(mirror, "rev-parse", "--verify", f"{revision}^{{commit}}").strip()
        if not _COMMIT_PATTERN.fullmatch(resolved):
            raise RepositoryError("Git did not resolve a full commit SHA")
        return resolved

    def _git(self, mirror: Path, *arguments: str) -> str:
        return self._run("git", f"--git-dir={mirror}", *arguments)

    def _git_allow_no_match(self, mirror: Path, *arguments: str) -> str:
        return self._run("git", f"--git-dir={mirror}", *arguments, allowed_codes={0, 1})

    @staticmethod
    def _run(*arguments: str, allowed_codes: tuple[int, ...] | set[int] = (0,)) -> str:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode not in allowed_codes:
            operation_index = (
                2 if len(arguments) > 2 and arguments[1].startswith("--git-dir=") else 1
            )
            operation = (
                arguments[operation_index] if len(arguments) > operation_index else "command"
            )
            raise RepositoryError(f"Git {operation} failed for the requested repository object")
        return result.stdout
