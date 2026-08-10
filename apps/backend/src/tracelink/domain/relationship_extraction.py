from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from tracelink.domain.enums import (
    EntityType,
    RelationshipClaimKind,
    RelationshipType,
)

SYMMETRIC_RELATIONSHIP_TYPES = frozenset(
    {
        RelationshipType.RELATED_TO,
        RelationshipType.PARTNER_OF,
        RelationshipType.SHARES_ADDRESS_WITH,
    }
)

MATERIALIZED_RELATIONSHIP_TYPES = frozenset(set(RelationshipType) - {RelationshipType.MENTIONED_IN})

RELATIONSHIP_TYPE_COMPATIBILITY: dict[
    RelationshipType, tuple[frozenset[EntityType] | None, frozenset[EntityType] | None]
] = {
    RelationshipType.DIRECTOR_OF: (
        frozenset({EntityType.PERSON}),
        frozenset({EntityType.COMPANY, EntityType.ORGANIZATION}),
    ),
    RelationshipType.OWNER_OF: (
        frozenset({EntityType.PERSON, EntityType.COMPANY}),
        frozenset({EntityType.COMPANY, EntityType.DOMAIN}),
    ),
    RelationshipType.EMPLOYEE_OF: (
        frozenset({EntityType.PERSON}),
        frozenset({EntityType.COMPANY, EntityType.ORGANIZATION}),
    ),
    RelationshipType.RELATED_TO: (None, None),
    RelationshipType.SHARES_ADDRESS_WITH: (
        frozenset({EntityType.COMPANY, EntityType.ORGANIZATION}),
        frozenset({EntityType.COMPANY, EntityType.ORGANIZATION}),
    ),
    RelationshipType.OWNS_DOMAIN: (
        frozenset({EntityType.PERSON, EntityType.COMPANY, EntityType.ORGANIZATION}),
        frozenset({EntityType.DOMAIN}),
    ),
    RelationshipType.MENTIONED_IN: (None, frozenset({EntityType.DOCUMENT})),
    RelationshipType.SUBSIDIARY_OF: (
        frozenset({EntityType.COMPANY}),
        frozenset({EntityType.COMPANY}),
    ),
    RelationshipType.PARTNER_OF: (
        frozenset({EntityType.PERSON, EntityType.COMPANY, EntityType.ORGANIZATION}),
        frozenset({EntityType.PERSON, EntityType.COMPANY, EntityType.ORGANIZATION}),
    ),
}

_PARTIAL_DATE = re.compile(r"^\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?$")


def validate_partial_date(value: str | None) -> str | None:
    if value is None:
        return None
    if not _PARTIAL_DATE.fullmatch(value):
        raise ValueError("temporal values must use YYYY, YYYY-MM, or YYYY-MM-DD")
    parts = [int(part) for part in value.split("-")]
    if len(parts) == 3:
        date(*parts)
    return value


def partial_date_bounds(value: str) -> tuple[date, date]:
    validate_partial_date(value)
    parts = [int(part) for part in value.split("-")]
    if len(parts) == 1:
        return date(parts[0], 1, 1), date(parts[0], 12, 31)
    if len(parts) == 2:
        last = calendar.monthrange(parts[0], parts[1])[1]
        return date(parts[0], parts[1], 1), date(parts[0], parts[1], last)
    parsed = date(*parts)
    return parsed, parsed


def temporal_ranges_overlap(
    left_start: str | None,
    left_end: str | None,
    right_start: str | None,
    right_end: str | None,
) -> bool:
    if not any((left_start, left_end)) or not any((right_start, right_end)):
        return False
    left_low = partial_date_bounds(left_start)[0] if left_start else date.min
    left_high = partial_date_bounds(left_end)[1] if left_end else date.max
    right_low = partial_date_bounds(right_start)[0] if right_start else date.min
    right_high = partial_date_bounds(right_end)[1] if right_end else date.max
    return left_low <= right_high and right_low <= left_high


def canonicalize_relationship_endpoints(
    source_entity_id: UUID,
    target_entity_id: UUID,
    relationship_type: RelationshipType,
) -> tuple[UUID, UUID]:
    if relationship_type in SYMMETRIC_RELATIONSHIP_TYPES and target_entity_id < source_entity_id:
        return target_entity_id, source_entity_id
    return source_entity_id, target_entity_id


def relationship_types_compatible(
    relationship_type: RelationshipType,
    source_type: EntityType,
    target_type: EntityType,
) -> bool:
    source_allowed, target_allowed = RELATIONSHIP_TYPE_COMPATIBILITY[relationship_type]
    return (source_allowed is None or source_type in source_allowed) and (
        target_allowed is None or target_type in target_allowed
    )


class ResolvedRelationshipMention(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mention_id: UUID
    entity_id: UUID
    entity_type: EntityType
    canonical_name: str = Field(min_length=1, max_length=500)
    surface_form: str = Field(min_length=1, max_length=500)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)


class RelationshipExtractionContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    investigation_id: UUID
    document_id: UUID
    chunk_index: int = Field(ge=0)


class ExtractedRelationshipCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_mention_id: UUID
    target_mention_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    type: RelationshipType
    claim_kind: RelationshipClaimKind = RelationshipClaimKind.AFFIRMS
    confidence: float = Field(ge=0, le=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=1)
    temporal_start: str | None = None
    temporal_end: str | None = None
    current_state: bool = False
    attributes: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_candidate(self) -> ExtractedRelationshipCandidate:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must both be present or absent")
        if self.start_offset is not None and self.end_offset is not None:
            if self.end_offset <= self.start_offset:
                raise ValueError("end_offset must be greater than start_offset")
        validate_partial_date(self.temporal_start)
        validate_partial_date(self.temporal_end)
        if self.temporal_start and self.temporal_end:
            if (
                partial_date_bounds(self.temporal_start)[0]
                > partial_date_bounds(self.temporal_end)[1]
            ):
                raise ValueError("temporal_end cannot be earlier than temporal_start")
        return self


class RelationshipExtractionProvider(Protocol):
    name: str

    async def extract(
        self,
        text: str,
        mentions: list[ResolvedRelationshipMention],
        allowed_types: frozenset[RelationshipType],
        context: RelationshipExtractionContext,
    ) -> list[ExtractedRelationshipCandidate]: ...


class RelationshipExtractionProviderError(RuntimeError):
    transient = False


class TransientRelationshipExtractionProviderError(RelationshipExtractionProviderError):
    transient = True


class RelationshipProviderOutputError(RelationshipExtractionProviderError):
    pass
