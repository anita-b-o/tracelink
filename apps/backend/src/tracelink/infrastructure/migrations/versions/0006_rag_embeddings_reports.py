"""Add grounded retrieval, embeddings, and persisted reports.

Revision ID: 0006_rag_embeddings_reports
Revises: 0005_relationship_evidence
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0006_rag_embeddings_reports"
down_revision: str | Sequence[str] | None = "0005_relationship_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

report_type = postgresql.ENUM(
    "EXECUTIVE_SUMMARY",
    "CORPORATE_PROFILE",
    "RELATIONSHIP_SUMMARY",
    "TIMELINE_SUMMARY",
    name="investigation_report_type",
    create_type=False,
)
report_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    name="investigation_report_status",
    create_type=False,
)


def upgrade() -> None:
    # Phase 1's table was an unused schema reservation. Embeddings are derived data and
    # are deliberately rebuilt under the dimensioned Phase 6 contract.
    op.drop_table("embedding_records")

    op.create_table(
        "retrieval_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer()),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', chunk_text)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        sa.CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="offsets_valid"),
        sa.CheckConstraint(
            "token_count IS NULL OR token_count >= 0", name="token_count_non_negative"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_retrieval_chunks"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_retrieval_chunk_document_index"),
    )
    op.create_index("ix_retrieval_chunks_document_id", "retrieval_chunks", ["document_id"])
    op.create_index("ix_retrieval_chunks_content_hash", "retrieval_chunks", ["content_hash"])
    op.create_index(
        "ix_retrieval_chunks_search_vector",
        "retrieval_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.create_table(
        "embedding_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding", VECTOR(1536), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("dimensions = 1536", name="dimensions_fixed"),
        sa.ForeignKeyConstraint(
            ["retrieval_chunk_id"], ["retrieval_chunks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_records"),
        sa.UniqueConstraint(
            "retrieval_chunk_id", "provider", "model", name="uq_embedding_chunk_provider_model"
        ),
    )
    op.create_index(
        "ix_embedding_records_retrieval_chunk_id",
        "embedding_records",
        ["retrieval_chunk_id"],
    )
    op.create_index("ix_embedding_records_content_hash", "embedding_records", ["content_hash"])
    op.create_index(
        "ix_embedding_records_provider_model",
        "embedding_records",
        ["provider", "model", "dimensions"],
    )

    bind = op.get_bind()
    report_type.create(bind, checkfirst=True)
    report_status.create(bind, checkfirst=True)
    op.create_table(
        "investigation_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("type", report_type, nullable=False),
        sa.Column(
            "status",
            report_status,
            server_default=sa.text("'PENDING'::investigation_report_status"),
            nullable=False,
        ),
        sa.Column("content", postgresql.JSONB()),
        sa.Column(
            "parameters", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active_celery_task_id", sa.String(length=255)),
        sa.Column("last_error_code", sa.String(length=100)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_investigation_reports"),
        sa.UniqueConstraint(
            "investigation_id",
            "type",
            "subject_entity_id",
            "input_fingerprint",
            name="uq_investigation_report_fingerprint",
            postgresql_nulls_not_distinct=True,
        ),
    )
    for column in (
        "investigation_id",
        "subject_entity_id",
        "type",
        "status",
        "input_fingerprint",
    ):
        op.create_index(f"ix_investigation_reports_{column}", "investigation_reports", [column])

    op.create_index(
        "ix_investigation_artifacts_investigation_document",
        "investigation_artifacts",
        ["investigation_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_artifacts_investigation_document",
        table_name="investigation_artifacts",
    )
    op.drop_table("investigation_reports")
    report_status.drop(op.get_bind(), checkfirst=True)
    report_type.drop(op.get_bind(), checkfirst=True)
    op.drop_table("embedding_records")
    op.drop_table("retrieval_chunks")

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
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_records"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_embedding_document_chunk"),
    )
    op.create_index("ix_embedding_records_document_id", "embedding_records", ["document_id"])
