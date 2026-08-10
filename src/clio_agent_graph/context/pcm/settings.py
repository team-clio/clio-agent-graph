"""PCM 영속 저장 설정."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PCMStorageSettings:
    """환경변수에서 한 번에 구성하는 PostgreSQL 및 Markdown 저장 설정."""

    database_url: str | None
    data_root: Path

    @classmethod
    def from_env(cls) -> "PCMStorageSettings":
        database_url = os.getenv("CLIO_PCM_DATABASE_URL")
        data_root = Path(os.getenv("CLIO_PCM_DATA_ROOT", ".clio/pcm-data")).expanduser()
        return cls(database_url=database_url, data_root=data_root)

    @property
    def persistent_enabled(self) -> bool:
        return bool(self.database_url)
