"""Add relationship candidate review audit timestamp.

Revision ID: 0007_workspace_review
Revises: 0006_rag_embeddings_reports
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_workspace_review"
down_revision: str | Sequence[str] | None = "0006_rag_embeddings_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "relationship_candidates",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("relationship_candidates", "reviewed_at")
