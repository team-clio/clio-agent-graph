"""Align retrieval documents with the current Bug-only Server schema.

Revision ID: 20260815_02
Revises: 20260731_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_02"
down_revision: str | Sequence[str] | None = "20260731_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the legacy occurrence reference when upgrading an existing Agent DB."""

    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("bug_retrieval_documents")}
    if "bug_report_id" not in columns:
        return
    # Legacy documents point to aggregated Bugs that V3 split; backfill is the only safe remap.
    op.execute("DELETE FROM bug_retrieval_documents")
    for foreign_key in inspector.get_foreign_keys("bug_retrieval_documents"):
        if foreign_key["constrained_columns"] == ["bug_report_id"]:
            op.drop_constraint(foreign_key["name"], "bug_retrieval_documents", type_="foreignkey")
    op.drop_column("bug_retrieval_documents", "bug_report_id")


def downgrade() -> None:
    """The removed occurrence table cannot be reconstructed from the Bug-only schema."""

    raise RuntimeError("Downgrading the Bug-only retrieval schema is not supported.")
