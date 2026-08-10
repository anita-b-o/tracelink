from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tracelink.domain.enums import (
    AssertionStatus,
    EntityType,
    InvestigationStatus,
    RelationshipType,
    ResearchTaskStatus,
    ResearchTaskType,
)
from tracelink.infrastructure.database import Base

JsonObject = dict[str, Any]


def enum_type(enum_class: type[Any], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Investigation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "investigations"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[InvestigationStatus] = mapped_column(
        enum_type(InvestigationStatus, "investigation_status"),
        default=InvestigationStatus.DRAFT,
        nullable=False,
        index=True,
    )

    tasks: Mapped[list[ResearchTask]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", passive_deletes=True
    )
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", passive_deletes=True
    )
    findings: Mapped[list[Finding]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", passive_deletes=True
    )


class ResearchTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_tasks"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name="task_dates_ordered",
        ),
        UniqueConstraint("investigation_id", "type", name="uq_research_task_plan_item"),
    )

    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ResearchTaskType] = mapped_column(
        enum_type(ResearchTaskType, "research_task_type"), nullable=False
    )
    status: Mapped[ResearchTaskStatus] = mapped_column(
        enum_type(ResearchTaskStatus, "research_task_status"),
        default=ResearchTaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[JsonObject | None] = mapped_column(JSONB)
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    active_celery_task_id: Mapped[str | None] = mapped_column(String(255))

    investigation: Mapped[Investigation] = relationship(back_populates="tasks")


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (Index("ix_entities_type_normalized_name", "type", "normalized_name"),)

    type: Mapped[EntityType] = mapped_column(enum_type(EntityType, "entity_type"), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )

    aliases: Mapped[list[EntityAlias]] = relationship(
        back_populates="entity", cascade="all, delete-orphan", passive_deletes=True
    )


class EntityAlias(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_alias", name="uq_entity_alias_normalized"),
    )

    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entity: Mapped[Entity] = relationship(back_populates="aliases")


class Relationship(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "relationships"
    __table_args__ = (
        CheckConstraint("source_entity_id <> target_entity_id", name="not_self_referential"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "first_observed_at IS NULL OR last_observed_at IS NULL "
            "OR last_observed_at >= first_observed_at",
            name="observation_dates_ordered",
        ),
        UniqueConstraint(
            "source_entity_id",
            "target_entity_id",
            "type",
            name="uq_relationship_directed_type",
        ),
        Index("ix_relationships_source_target", "source_entity_id", "target_entity_id"),
    )

    source_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    target_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    type: Mapped[RelationshipType] = mapped_column(
        enum_type(RelationshipType, "relationship_type"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[AssertionStatus] = mapped_column(
        enum_type(AssertionStatus, "relationship_status"), nullable=False, index=True
    )
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )


class Source(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (Index("ix_sources_url_identity", "url_hash", "normalized_url"),)

    type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    publisher: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    documents: Mapped[list[Document]] = relationship(back_populates="source", passive_deletes=True)


class Document(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_document_source_hash"),
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source: Mapped[Source] = relationship(back_populates="documents")
    embeddings: Mapped[list[EmbeddingRecord]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Evidence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "entity_id IS NOT NULL OR relationship_id IS NOT NULL", name="target_required"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    )

    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    relationship_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("relationships.id", ondelete="RESTRICT"), index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), index=True
    )
    excerpt: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[str | None] = mapped_column(String(500))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    investigation: Mapped[Investigation] = relationship(back_populates="evidence")


class Finding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "relevance IS NULL OR (relevance >= 0 AND relevance <= 1)",
            name="relevance_range",
        ),
    )

    investigation_id: Mapped[UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[AssertionStatus] = mapped_column(
        enum_type(AssertionStatus, "finding_status"), nullable=False, index=True
    )
    relevance: Mapped[float | None] = mapped_column(Float)

    investigation: Mapped[Investigation] = relationship(back_populates="findings")


class EmbeddingRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "embedding_records"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        UniqueConstraint("document_id", "chunk_index", name="uq_embedding_document_chunk"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="embeddings")
