"""CLIO_DATABASE_URL에 Python 소유 RAG migration을 적용한다."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from clio_agent_graph.workflows.reporting.retrieval.postgres import normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv("CLIO_DATABASE_URL")
if database_url is None or not database_url.strip():
    raise RuntimeError("CLIO_DATABASE_URL is required to run migrations.")
config.set_main_option("sqlalchemy.url", normalize_database_url(database_url))

# 현재 migration은 SQL로 명시한 schema만 관리하므로 ORM metadata를 사용하지 않는다.
target_metadata = None


def run_migrations_offline() -> None:
    """DB 연결 없이 migration SQL을 생성한다."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """실제 PostgreSQL 연결에서 migration을 실행한다."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
