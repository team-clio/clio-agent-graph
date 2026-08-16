"""Remove the legacy Bug occurrence reference and Spring database FKs.

Revision ID: 20260813_01
Revises: 20260731_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_01"
down_revision: str | None = "20260731_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Retrieval snapshots retain only Agent-owned identifiers."""

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "bug_retrieval_documents" not in inspector.get_table_names():
        return
    foreign_keys = inspector.get_foreign_keys("bug_retrieval_documents")
    for foreign_key in foreign_keys:
        name = foreign_key.get("name")
        if name:
            op.drop_constraint(name, "bug_retrieval_documents", type_="foreignkey")
    columns = {column["name"] for column in inspector.get_columns("bug_retrieval_documents")}
    op.execute(
        """
        UPDATE bug_retrieval_documents
        SET normalized_report =
            (normalized_report - 'bug_report_id') || jsonb_build_object('bug_id', bug_id)
        WHERE normalized_report ? 'bug_report_id'
           OR NOT (normalized_report ? 'bug_id')
        """
    )
    if "bug_report_id" in columns:
        op.drop_column("bug_retrieval_documents", "bug_report_id")


def downgrade() -> None:
    """Removed Spring references are intentionally not recreated."""
