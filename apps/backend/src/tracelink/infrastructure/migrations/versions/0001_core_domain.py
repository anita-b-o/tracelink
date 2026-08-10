"""Create the TraceLink core domain schema.

Revision ID: 0001_core_domain
Revises:
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0001_core_domain"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

investigation_status = postgresql.ENUM(
    "DRAFT",
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "PARTIAL",
    name="investigation_status",
    create_type=False,
)
research_task_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    name="research_task_status",
    create_type=False,
)
entity_type = postgresql.ENUM(
    "PERSON",
    "COMPANY",
    "ORGANIZATION",
    "DOMAIN",
    "ADDRESS",
    "DOCUMENT",
    name="entity_type",
    create_type=False,
)
relationship_type = postgresql.ENUM(
    "DIRECTOR_OF",
    "OWNER_OF",
    "EMPLOYEE_OF",
    "RELATED_TO",
    "SHARES_ADDRESS_WITH",
    "OWNS_DOMAIN",
    "MENTIONED_IN",
    "SUBSIDIARY_OF",
    "PARTNER_OF",
    name="relationship_type",
    create_type=False,
)
assertion_values = ("CONFIRMED", "PROBABLE", "POSSIBLE", "UNVERIFIED", "CONTRADICTED")
relationship_status = postgresql.ENUM(
    *assertion_values, name="relationship_status", create_type=False
)
finding_status = postgresql.ENUM(*assertion_values, name="finding_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for enum in (
        investigation_status,
        research_task_status,
        entity_type,
        relationship_type,
        relationship_status,
        finding_status,
    ):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "investigations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column(
            "status",
            investigation_status,
            server_default=sa.text("'DRAFT'::investigation_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investigations"),
    )
    op.create_index("ix_investigations_status", "investigations", ["status"])

    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", entity_type, nullable=False),
        sa.Column("canonical_name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entities"),
    )
    op.create_index("ix_entities_normalized_name", "entities", ["normalized_name"])
    op.create_index("ix_entities_type_normalized_name", "entities", ["type", "normalized_name"])

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("publisher", sa.String(length=300)),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
    )
    op.create_index("ix_sources_type", "sources", ["type"])
    op.create_index("ix_sources_url_hash", "sources", ["url_hash"])
    op.create_index("ix_sources_retrieved_at", "sources", ["retrieved_at"])

    op.create_table(
        "research_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            research_task_status,
            server_default=sa.text("'PENDING'::research_task_status"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=100)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name="task_dates_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name="fk_research_tasks_investigation_id_investigations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_research_tasks"),
    )
    op.create_index("ix_research_tasks_investigation_id", "research_tasks", ["investigation_id"])
    op.create_index("ix_research_tasks_status", "research_tasks", ["status"])

    op.create_table(
        "entity_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=500), nullable=False),
        sa.Column("normalized_alias", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name="fk_entity_aliases_entity_id_entities",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_aliases"),
        sa.UniqueConstraint("entity_id", "normalized_alias", name="uq_entity_alias_normalized"),
    )
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])
    op.create_index("ix_entity_aliases_normalized_alias", "entity_aliases", ["normalized_alias"])

    op.create_table(
        "relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", relationship_type, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", relationship_status, nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True)),
        sa.Column("last_observed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_entity_id <> target_entity_id",
            name="not_self_referential",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint(
            "first_observed_at IS NULL OR last_observed_at IS NULL "
            "OR last_observed_at >= first_observed_at",
            name="observation_dates_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["source_entity_id"],
            ["entities.id"],
            name="fk_relationships_source_entity_id_entities",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["entities.id"],
            name="fk_relationships_target_entity_id_entities",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_relationships"),
        sa.UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "type",
            name="uq_relationship_directed_type",
        ),
    )
    op.create_index("ix_relationships_source_entity_id", "relationships", ["source_entity_id"])
    op.create_index("ix_relationships_target_entity_id", "relationships", ["target_entity_id"])
    op.create_index("ix_relationships_status", "relationships", ["status"])
    op.create_index(
        "ix_relationships_source_target",
        "relationships",
        ["source_entity_id", "target_entity_id"],
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_documents_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_document_source_hash"),
    )
    op.create_index("ix_documents_source_id", "documents", ["source_id"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True)),
        sa.Column("relationship_id", postgresql.UUID(as_uuid=True)),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("excerpt", sa.Text()),
        sa.Column("locator", sa.String(length=500)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "entity_id IS NOT NULL OR relationship_id IS NOT NULL",
            name="target_required",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name="fk_evidence_investigation_id_investigations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_evidence_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_evidence_document_id_documents",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            ["relationships.id"],
            name="fk_evidence_relationship_id_relationships",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name="fk_evidence_entity_id_entities",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
    )
    for column in (
        "investigation_id",
        "source_id",
        "document_id",
        "relationship_id",
        "entity_id",
    ):
        op.create_index(f"ix_evidence_{column}", "evidence", [column])

    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", finding_status, nullable=False),
        sa.Column("relevance", sa.Float()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint(
            "relevance IS NULL OR (relevance >= 0 AND relevance <= 1)",
            name="relevance_range",
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name="fk_findings_investigation_id_investigations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_findings"),
    )
    op.create_index("ix_findings_investigation_id", "findings", ["investigation_id"])
    op.create_index("ix_findings_status", "findings", ["status"])

    op.create_table(
        "embedding_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_embedding_records_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_records"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_embedding_document_chunk"),
    )
    op.create_index("ix_embedding_records_document_id", "embedding_records", ["document_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "embedding_records",
        "findings",
        "evidence",
        "documents",
        "relationships",
        "entity_aliases",
        "research_tasks",
        "sources",
        "entities",
        "investigations",
    ):
        op.drop_table(table)

    for enum in (
        finding_status,
        relationship_status,
        relationship_type,
        entity_type,
        research_task_status,
        investigation_status,
    ):
        enum.drop(bind, checkfirst=True)
