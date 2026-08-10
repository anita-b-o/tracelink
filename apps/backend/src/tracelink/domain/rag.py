from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GroundedClaim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str] = Field(min_length=1, max_length=20)
    confidence: float = Field(ge=0, le=1)


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    claims: list[GroundedClaim] = Field(default_factory=list, max_length=50)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class GeneratedReportSection(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    heading: str = Field(min_length=1, max_length=300)
    claims: list[GroundedClaim] = Field(default_factory=list, max_length=100)


class GeneratedReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    summary_claims: list[GroundedClaim] = Field(default_factory=list, max_length=50)
    sections: list[GeneratedReportSection] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    source_ids: tuple[UUID, ...] = ()
    document_ids: tuple[UUID, ...] = ()
    entity_ids: tuple[UUID, ...] = ()
    relationship_types: tuple[str, ...] = ()
    published_from: datetime | None = None
    published_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    chunk_index: int
    chunk_text: str
    start_offset: int
    end_offset: int
    source_url: str
    source_title: str | None
    published_at: datetime | None
    semantic_score: float
    lexical_score: float
    evidence_boost: float
    combined_score: float
    matched_entity_ids: tuple[UUID, ...] = ()
    matched_relationship_types: tuple[str, ...] = ()


@dataclass(slots=True)
class GroundedContext:
    investigation_id: UUID
    hits: list[RetrievalHit]
    payload: dict[str, Any]
    allowed_citations: dict[str, dict[str, Any]]
    evidence_count: int
    contradictions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class GroundedAnswerResult:
    answer: str
    abstained: bool
    confidence: float
    claims: list[GroundedClaim]
    citations: list[dict[str, Any]]
    limitations: list[str]
    contradictions: list[dict[str, Any]]
