import pytest

from clio_agent_graph.retrieval.errors import RetrievalConfigurationError
from clio_agent_graph.retrieval.postgres import (
    PostgresRetrievalRepository,
    normalize_database_url,
)


def test_postgres_repository_does_not_connect_during_construction(monkeypatch) -> None:
    monkeypatch.delenv("CLIO_DATABASE_URL", raising=False)
    repository = PostgresRetrievalRepository()

    assert repository._engine is None

    with pytest.raises(RetrievalConfigurationError):
        repository._get_engine()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "postgresql://clio:clio@localhost:5432/clio",
            "postgresql+psycopg://clio:clio@localhost:5432/clio",
        ),
        (
            "postgres://clio:clio@localhost:5432/clio",
            "postgresql+psycopg://clio:clio@localhost:5432/clio",
        ),
        (
            "postgresql+psycopg://clio:clio@localhost:5432/clio",
            "postgresql+psycopg://clio:clio@localhost:5432/clio",
        ),
    ],
)
def test_database_url_uses_psycopg3_driver(source: str, expected: str) -> None:
    assert normalize_database_url(source) == expected
