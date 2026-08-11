from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from tracelink.api.schemas.sources import SourceSummaryRead
from tracelink.domain.enums import EntityResolutionCandidateStatus, EntityType

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class EntityCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    type: EntityType = Field(strict=False)
    canonical_name: Name
    aliases: list[Name] = Field(default_factory=list, max_length=100)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class EntityAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alias: str
    normalized_alias: str
    created_at: datetime


class EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    type: EntityType
    canonical_name: str
    normalized_name: str
    metadata: dict[str, JsonValue] = Field(validation_alias="metadata_")
    aliases: list[EntityAliasRead]
    created_at: datetime
    updated_at: datetime


class EntityMentionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    investigation_id: UUID
    document_id: UUID
    entity_id: UUID | None
    entity_type: EntityType
    surface_form: str
    normalized_form: str
    start_offset: int | None
    end_offset: int | None
    chunk_index: int | None
    extraction_method: str
    confidence: float
    metadata: dict[str, JsonValue] = Field(validation_alias="metadata_")
    created_at: datetime


class InvestigationEntityRead(EntityRead):
    mention_count: int


class EntityMentionDetailRead(EntityMentionRead):
    source: SourceSummaryRead
    document_title: str | None
    context_preview: str


class EntityResolutionCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    investigation_id: UUID
    mention_id: UUID
    candidate_entity_id: UUID
    score: float
    status: EntityResolutionCandidateStatus
    signals: dict[str, JsonValue]
    created_at: datetime
    reviewed_at: datetime | None


class EntityResolutionCandidateDetailRead(EntityResolutionCandidateRead):
    mention: EntityMentionDetailRead
    provisional_entity: EntityRead | None
    candidate_entity: EntityRead
