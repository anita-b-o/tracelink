"""Add the asynchronous investigation workflow fields.

Revision ID: 0002_investigation_workflow
Revises: 0001_core_domain
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_investigation_workflow"
down_revision: str | Sequence[str] | None = "0001_core_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

research_task_type = postgresql.ENUM(
    "IDENTIFY_ENTITY",
    "WEB_SEARCH",
    "DOMAIN_LOOKUP",
    "PUBLIC_MENTIONS",
    name="research_task_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    research_task_type.create(bind, checkfirst=True)
    op.execute(
        "ALTER TABLE research_tasks ALTER COLUMN type TYPE research_task_type "
        "USING type::research_task_type"
    )
    op.add_column("research_tasks", sa.Column("result", postgresql.JSONB(), nullable=True))
    op.add_column(
        "research_tasks", sa.Column("last_error_code", sa.String(length=100), nullable=True)
    )
    op.add_column("research_tasks", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.add_column(
        "research_tasks", sa.Column("active_celery_task_id", sa.String(length=255), nullable=True)
    )
    op.create_unique_constraint(
        "uq_research_task_plan_item", "research_tasks", ["investigation_id", "type"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_constraint("uq_research_task_plan_item", "research_tasks", type_="unique")
    op.drop_column("research_tasks", "active_celery_task_id")
    op.drop_column("research_tasks", "last_error_message")
    op.drop_column("research_tasks", "last_error_code")
    op.drop_column("research_tasks", "result")
    op.execute("ALTER TABLE research_tasks ALTER COLUMN type TYPE VARCHAR(100) USING type::text")
    research_task_type.drop(bind, checkfirst=True)
