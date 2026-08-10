from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from tracelink.domain.enums import (
    AssertionStatus,
    EntityType,
    EvidenceType,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipType,
)


class RelationshipEntitySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: EntityType
    canonical_name: str


class RelationshipRead(BaseModel):
    id: UUID
    source_entity: RelationshipEntitySummary
    target_entity: RelationshipEntitySummary
    type: RelationshipType
    confidence: float
    status: AssertionStatus
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    temporal_start: str | None
    temporal_end: str | None
    evidence_count: int


class RelationshipCandidateRead(BaseModel):
    id: UUID
    investigation_id: UUID
    document_id: UUID
    source_entity: RelationshipEntitySummary
    target_entity: RelationshipEntitySummary
    type: RelationshipType
    claim_kind: RelationshipClaimKind
    confidence: float
    score: float
    status: RelationshipCandidateStatus
    extraction_method: str
    signals: dict[str, JsonValue]
    temporal_start: str | None
    temporal_end: str | None
    evidence_preview: str | None
    created_at: datetime


class RelationshipEvidenceRead(BaseModel):
    id: UUID
    investigation_id: UUID
    source_id: UUID
    document_id: UUID | None
    relationship_id: UUID | None
    evidence_type: EvidenceType
    confidence: float
    start_offset: int | None
    end_offset: int | None
    locator: str | None
    preview: str | None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime
