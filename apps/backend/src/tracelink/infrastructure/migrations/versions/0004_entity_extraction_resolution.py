"""Add entity extraction, provenance, and resolution persistence.

Revision ID: 0004_entity_extraction
Revises: 0003_research_connectors
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_entity_extraction"
down_revision: str | Sequence[str] | None = "0003_research_connectors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

resolution_candidate_status = postgresql.ENUM(
    "PENDING",
    "ACCEPTED",
    "REJECTED",
    "AUTO_MATCHED",
    name="entity_resolution_candidate_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    resolution_candidate_status.create(bind, checkfirst=True)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column("entities", sa.Column("comparison_key", sa.String(length=500), nullable=True))
    op.execute("UPDATE entities SET comparison_key = normalized_name")
    op.alter_column("entities", "comparison_key", nullable=False)
    op.create_index("ix_entities_comparison_key", "entities", ["comparison_key"])
    op.create_index(
        "ix_entities_comparison_key_trgm",
        "entities",
        ["comparison_key"],
        postgresql_using="gin",
        postgresql_ops={"comparison_key": "gin_trgm_ops"},
    )

    op.add_column(
        "entity_aliases", sa.Column("comparison_key", sa.String(length=500), nullable=True)
    )
    op.execute("UPDATE entity_aliases SET comparison_key = normalized_alias")
    op.alter_column("entity_aliases", "comparison_key", nullable=False)
    op.create_index("ix_entity_aliases_comparison_key", "entity_aliases", ["comparison_key"])
    op.create_index(
        "ix_entity_aliases_comparison_key_trgm",
        "entity_aliases",
        ["comparison_key"],
        postgresql_using="gin",
        postgresql_ops={"comparison_key": "gin_trgm_ops"},
    )
    op.create_unique_constraint(
        "uq_entity_alias_comparison_key", "entity_aliases", ["entity_id", "comparison_key"]
    )

    op.create_unique_constraint("uq_document_id_source", "documents", ["id", "source_id"])
    op.create_table(
        "investigation_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name="fk_investigation_artifacts_investigation_id_investigations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_investigation_artifacts_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "source_id"],
            ["documents.id", "documents.source_id"],
            name="fk_investigation_artifacts_document_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_artifacts"),
    )
    op.execute(
        "ALTER TABLE investigation_artifacts ADD CONSTRAINT uq_investigation_artifact "
        "UNIQUE NULLS NOT DISTINCT (investigation_id, source_id, document_id)"
    )
    for column in ("investigation_id", "source_id", "document_id"):
        op.create_index(f"ix_investigation_artifacts_{column}", "investigation_artifacts", [column])

    op.create_table(
        "entity_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "entity_type", postgresql.ENUM(name="entity_type", create_type=False), nullable=False
        ),
        sa.Column("surface_form", sa.String(length=500), nullable=False),
        sa.Column("normalized_form", sa.String(length=500), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint(
            "chunk_index IS NULL OR chunk_index >= 0", name="chunk_index_non_negative"
        ),
        sa.CheckConstraint(
            "(start_offset IS NULL AND end_offset IS NULL) OR "
            "(start_offset >= 0 AND end_offset > start_offset)",
            name="offsets_valid",
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name="fk_entity_mentions_investigation_id_investigations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_entity_mentions_document_id_documents",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name="fk_entity_mentions_entity_id_entities",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_mentions"),
        sa.UniqueConstraint(
            "investigation_id",
            "document_id",
            "fingerprint",
            name="uq_entity_mention_fingerprint",
        ),
        sa.UniqueConstraint("id", "investigation_id", name="uq_entity_mention_id_investigation"),
    )
    for column in (
        "investigation_id",
        "document_id",
        "entity_id",
        "entity_type",
        "normalized_form",
    ):
        op.create_index(f"ix_entity_mentions_{column}", "entity_mentions", [column])

    op.create_table(
        "entity_resolution_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mention_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", resolution_candidate_status, nullable=False),
        sa.Column(
            "signals", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name="fk_entity_resolution_candidates_investigation_id_investigations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mention_id", "investigation_id"],
            ["entity_mentions.id", "entity_mentions.investigation_id"],
            name="fk_resolution_candidates_mention_investigation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_entity_id"],
            ["entities.id"],
            name="fk_entity_resolution_candidates_candidate_entity_id_entities",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_resolution_candidates"),
        sa.UniqueConstraint(
            "mention_id", "candidate_entity_id", name="uq_resolution_candidate_mention_entity"
        ),
    )
    for column in ("investigation_id", "mention_id", "candidate_entity_id", "status"):
        op.create_index(
            f"ix_entity_resolution_candidates_{column}",
            "entity_resolution_candidates",
            [column],
        )


def downgrade() -> None:
    op.drop_table("entity_resolution_candidates")
    op.drop_table("entity_mentions")
    op.drop_table("investigation_artifacts")
    op.drop_constraint("uq_document_id_source", "documents", type_="unique")
    op.drop_constraint("uq_entity_alias_comparison_key", "entity_aliases", type_="unique")
    op.drop_index("ix_entity_aliases_comparison_key_trgm", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_comparison_key", table_name="entity_aliases")
    op.drop_column("entity_aliases", "comparison_key")
    op.drop_index("ix_entities_comparison_key_trgm", table_name="entities")
    op.drop_index("ix_entities_comparison_key", table_name="entities")
    op.drop_column("entities", "comparison_key")
    resolution_candidate_status.drop(op.get_bind(), checkfirst=True)
