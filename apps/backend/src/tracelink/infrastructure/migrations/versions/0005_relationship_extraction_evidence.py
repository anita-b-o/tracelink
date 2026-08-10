"""Add relationship extraction candidates and auditable evidence.

Revision ID: 0005_relationship_evidence
Revises: 0004_entity_extraction
Create Date: 2026-08-10
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_relationship_evidence"
down_revision: str | Sequence[str] | None = "0004_entity_extraction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

candidate_status = postgresql.ENUM(
    "PENDING",
    "ACCEPTED",
    "REJECTED",
    "AUTO_ACCEPTED",
    "CONTRADICTED",
    name="relationship_candidate_status",
    create_type=False,
)
claim_kind = postgresql.ENUM(
    "AFFIRMS", "NEGATES", "ENDS", name="relationship_claim_kind", create_type=False
)
evidence_type = postgresql.ENUM(
    "SUPPORTING",
    "CONTRADICTING",
    "TEMPORAL_UPDATE",
    name="evidence_type",
    create_type=False,
)
relationship_type = postgresql.ENUM(name="relationship_type", create_type=False)


def _canonicalize_symmetric_relationships() -> None:
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT id, source_entity_id, target_entity_id, type::text AS type, confidence, "
                "status::text AS status, first_observed_at, last_observed_at "
                "FROM relationships WHERE type::text IN "
                "('RELATED_TO', 'PARTNER_OF', 'SHARES_ADDRESS_WITH') ORDER BY id"
            )
        ).mappings()
    )
    grouped: dict[tuple[object, object, str], list[sa.RowMapping]] = {}
    for row in rows:
        source, target = sorted((row["source_entity_id"], row["target_entity_id"]))
        grouped.setdefault((source, target, str(row["type"])), []).append(row)
    status_rank = {
        "UNVERIFIED": 0,
        "POSSIBLE": 1,
        "PROBABLE": 2,
        "CONFIRMED": 3,
        "CONTRADICTED": 4,
    }
    for (source, target, _), duplicates in grouped.items():
        keeper = duplicates[0]
        duplicate_ids = [row["id"] for row in duplicates[1:]]
        if duplicate_ids:
            bind.execute(
                sa.text(
                    "UPDATE evidence SET relationship_id = :keeper "
                    "WHERE relationship_id = ANY(:ids)"
                ),
                {"keeper": keeper["id"], "ids": duplicate_ids},
            )
            bind.execute(
                sa.text("DELETE FROM relationships WHERE id = ANY(:ids)"), {"ids": duplicate_ids}
            )
        first_values = [row["first_observed_at"] for row in duplicates if row["first_observed_at"]]
        last_values = [row["last_observed_at"] for row in duplicates if row["last_observed_at"]]
        status = max(duplicates, key=lambda row: status_rank[str(row["status"])])["status"]
        bind.execute(
            sa.text(
                "UPDATE relationships SET source_entity_id = :source, target_entity_id = :target, "
                "confidence = :confidence, status = CAST(:status AS relationship_status), "
                "first_observed_at = :first, last_observed_at = :last WHERE id = :id"
            ),
            {
                "source": source,
                "target": target,
                "confidence": max(float(row["confidence"]) for row in duplicates),
                "status": status,
                "first": min(first_values) if first_values else None,
                "last": max(last_values) if last_values else None,
                "id": keeper["id"],
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (candidate_status, claim_kind, evidence_type):
        enum.create(bind, checkfirst=True)

    op.add_column("relationships", sa.Column("temporal_start", sa.String(length=10)))
    op.add_column("relationships", sa.Column("temporal_end", sa.String(length=10)))
    _canonicalize_symmetric_relationships()
    op.create_check_constraint(
        "symmetric_endpoints_canonical",
        "relationships",
        "type::text NOT IN ('RELATED_TO', 'PARTNER_OF', 'SHARES_ADDRESS_WITH') "
        "OR source_entity_id < target_entity_id",
    )
    op.create_check_constraint(
        "temporal_values_iso_partial",
        "relationships",
        "(temporal_start IS NULL OR temporal_start ~ "
        "'^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$') AND "
        "(temporal_end IS NULL OR temporal_end ~ "
        "'^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$')",
    )

    op.create_table(
        "relationship_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", relationship_type, nullable=False),
        sa.Column("claim_kind", claim_kind, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("supporting_text", sa.String(length=1000)),
        sa.Column("start_offset", sa.Integer()),
        sa.Column("end_offset", sa.Integer()),
        sa.Column("temporal_start", sa.String(length=10)),
        sa.Column("temporal_end", sa.String(length=10)),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "signals", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("status", candidate_status, nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        sa.CheckConstraint(
            "(start_offset IS NULL AND end_offset IS NULL) OR "
            "(start_offset >= 0 AND end_offset > start_offset)",
            name="offsets_valid",
        ),
        sa.CheckConstraint(
            "(temporal_start IS NULL OR temporal_start ~ "
            "'^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$') AND "
            "(temporal_end IS NULL OR temporal_end ~ "
            "'^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$')",
            name="temporal_values_iso_partial",
        ),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_entity_id"], ["entities.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_relationship_candidates"),
        sa.UniqueConstraint(
            "investigation_id",
            "document_id",
            "fingerprint",
            name="uq_relationship_candidate_fingerprint",
        ),
    )
    for column in (
        "investigation_id",
        "document_id",
        "source_entity_id",
        "target_entity_id",
        "status",
    ):
        op.create_index(f"ix_relationship_candidates_{column}", "relationship_candidates", [column])
    op.create_index(
        "ix_relationship_candidates_identity",
        "relationship_candidates",
        ["investigation_id", "source_entity_id", "target_entity_id", "type"],
    )

    op.add_column("evidence", sa.Column("start_offset", sa.Integer()))
    op.add_column("evidence", sa.Column("end_offset", sa.Integer()))
    op.add_column(
        "evidence",
        sa.Column(
            "evidence_type",
            evidence_type,
            server_default=sa.text("'SUPPORTING'::evidence_type"),
            nullable=False,
        ),
    )
    op.add_column(
        "evidence",
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.add_column("evidence", sa.Column("fingerprint", sa.String(length=64)))
    evidence_rows = bind.execute(sa.text("SELECT id FROM evidence")).mappings()
    for row in evidence_rows:
        fingerprint = hashlib.sha256(f"legacy:{row['id']}".encode()).hexdigest()
        bind.execute(
            sa.text("UPDATE evidence SET fingerprint = :fingerprint WHERE id = :id"),
            {"fingerprint": fingerprint, "id": row["id"]},
        )
    op.alter_column("evidence", "fingerprint", nullable=False)
    op.create_check_constraint(
        "offsets_valid",
        "evidence",
        "(start_offset IS NULL AND end_offset IS NULL) OR "
        "(start_offset >= 0 AND end_offset > start_offset)",
    )
    op.create_unique_constraint(
        "uq_evidence_investigation_fingerprint",
        "evidence",
        ["investigation_id", "fingerprint"],
    )
    op.execute(
        "INSERT INTO investigation_artifacts (id, investigation_id, source_id, document_id) "
        "SELECT gen_random_uuid(), e.investigation_id, e.source_id, e.document_id FROM evidence e "
        "WHERE e.document_id IS NOT NULL ON CONFLICT ON CONSTRAINT uq_investigation_artifact "
        "DO NOTHING"
    )
    op.create_foreign_key(
        "fk_evidence_document_source",
        "evidence",
        "documents",
        ["document_id", "source_id"],
        ["id", "source_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_evidence_investigation_artifact",
        "evidence",
        "investigation_artifacts",
        ["investigation_id", "source_id", "document_id"],
        ["investigation_id", "source_id", "document_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_evidence_investigation_artifact", "evidence", type_="foreignkey")
    op.drop_constraint("fk_evidence_document_source", "evidence", type_="foreignkey")
    op.drop_constraint("uq_evidence_investigation_fingerprint", "evidence", type_="unique")
    op.drop_constraint("offsets_valid", "evidence", type_="check")
    op.drop_column("evidence", "fingerprint")
    op.drop_column("evidence", "metadata")
    op.drop_column("evidence", "evidence_type")
    op.drop_column("evidence", "end_offset")
    op.drop_column("evidence", "start_offset")

    op.drop_table("relationship_candidates")
    op.drop_constraint("temporal_values_iso_partial", "relationships", type_="check")
    op.drop_constraint("symmetric_endpoints_canonical", "relationships", type_="check")
    op.drop_column("relationships", "temporal_end")
    op.drop_column("relationships", "temporal_start")

    evidence_type.drop(op.get_bind(), checkfirst=True)
    claim_kind.drop(op.get_bind(), checkfirst=True)
    candidate_status.drop(op.get_bind(), checkfirst=True)
