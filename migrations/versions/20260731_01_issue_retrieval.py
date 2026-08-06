"""Issue Retrieval snapshot과 embedding schema.

Revision ID: 20260731_01
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260731_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """기존 embedding을 보존하고 Python 소유 retrieval schema를 만든다."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "bug_embeddings" in tables:
        columns = {column["name"] for column in inspector.get_columns("bug_embeddings")}
        if "retrieval_document_id" not in columns:
            if "legacy_bug_embeddings" in tables:
                raise RuntimeError(
                    "Both legacy_bug_embeddings and a legacy-shaped bug_embeddings table exist."
                )
            op.rename_table("bug_embeddings", "legacy_bug_embeddings")

    op.create_table(
        "bug_retrieval_documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("bug_id", sa.BigInteger(), nullable=False),
        sa.Column("bug_report_id", sa.BigInteger(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column("normalized_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column(
            "error_codes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "stack_frames",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bug_id"], ["bugs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bug_report_id"], ["bug_occurrences.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("bug_id", "document_version", name="uk_bug_retrieval_doc_version"),
    )
    op.create_index(
        "uk_bug_retrieval_doc_active",
        "bug_retrieval_documents",
        ["bug_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_index(
        "ix_bug_retrieval_doc_project_active",
        "bug_retrieval_documents",
        ["project_id", "active"],
    )
    op.create_index(
        "ix_bug_retrieval_doc_error_type",
        "bug_retrieval_documents",
        ["project_id", "error_type"],
    )
    op.execute(
        "CREATE INDEX ix_bug_retrieval_doc_error_codes "
        "ON bug_retrieval_documents USING gin (error_codes)"
    )
    op.execute(
        "CREATE INDEX ix_bug_retrieval_doc_stack_frames "
        "ON bug_retrieval_documents USING gin (stack_frames)"
    )
    op.execute(
        "CREATE INDEX ix_bug_retrieval_doc_search_trgm "
        "ON bug_retrieval_documents USING gin (search_text gin_trgm_ops)"
    )

    # dimension은 별도 컬럼으로 검사한다. v1은 ANN 없이 model별 exact scan을 사용한다.
    op.create_table(
        "bug_embeddings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("retrieval_document_id", sa.BigInteger(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_document_id"],
            ["bug_retrieval_documents.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "retrieval_document_id",
            "embedding_model",
            name="uk_bug_embedding_document_model",
        ),
    )
    op.create_index(
        "ix_bug_embedding_model_dimension",
        "bug_embeddings",
        ["embedding_model", "embedding_dimension"],
    )


def downgrade() -> None:
    """새 Python 소유 테이블만 제거하며 legacy 데이터는 그대로 보존한다."""

    op.drop_index("ix_bug_embedding_model_dimension", table_name="bug_embeddings")
    op.drop_table("bug_embeddings")
    op.drop_index("ix_bug_retrieval_doc_search_trgm", table_name="bug_retrieval_documents")
    op.drop_index("ix_bug_retrieval_doc_stack_frames", table_name="bug_retrieval_documents")
    op.drop_index("ix_bug_retrieval_doc_error_codes", table_name="bug_retrieval_documents")
    op.drop_index("ix_bug_retrieval_doc_error_type", table_name="bug_retrieval_documents")
    op.drop_index("ix_bug_retrieval_doc_project_active", table_name="bug_retrieval_documents")
    op.drop_index("uk_bug_retrieval_doc_active", table_name="bug_retrieval_documents")
    op.drop_table("bug_retrieval_documents")
