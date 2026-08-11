from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from tracelink.domain.enums import (
    InvestigationReportStatus,
    InvestigationReportType,
    RelationshipType,
)
from tracelink.domain.rag import GeneratedReportSection, GroundedClaim

SearchQuery = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
RelationshipTypeInput = Annotated[RelationshipType, Field(strict=False)]


class RetrievalFilterInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    source_ids: list[UUID] = Field(default_factory=list, max_length=50)
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)
    entity_ids: list[UUID] = Field(default_factory=list, max_length=50)
    relationship_types: list[RelationshipTypeInput] = Field(default_factory=list, max_length=50)
    published_from: AwareDatetime | None = None
    published_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> RetrievalFilterInput:
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_to < self.published_from
        ):
            raise ValueError("published_to must not precede published_from")
        return self


class SearchRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    query: SearchQuery
    top_k: int | None = Field(default=None, ge=1, le=50)
    filters: RetrievalFilterInput = Field(default_factory=RetrievalFilterInput)


class SearchHitRead(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

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
    matched_entity_ids: list[UUID]
    matched_relationship_types: list[str]


class AskRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    question: SearchQuery


class CitationRead(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: Literal["EVIDENCE", "CHUNK", "DOCUMENT", "SOURCE"]
    evidence_id: UUID | None = None
    chunk_id: UUID | None = None
    document_id: UUID | None = None
    source_id: UUID | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    source_url: str | None = None
    excerpt: str | None = None
    confidence: float | None = None


class GroundedAnswerRead(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    answer: str
    abstained: bool
    confidence: float
    claims: list[GroundedClaim]
    citations: list[CitationRead]
    limitations: list[str]
    contradictions: list[dict[str, Any]]


class ReportCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    type: InvestigationReportType = Field(strict=False)
    subject_entity_id: UUID | None = None


class InvestigationReportSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    investigation_id: UUID
    subject_entity_id: UUID | None
    type: InvestigationReportType
    status: InvestigationReportStatus
    provider: str
    model: str
    input_fingerprint: str
    attempts: int
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class ReportTimelineItemRead(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    date: str
    kind: str


class ReportContentRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    abstained: bool
    executive_summary: str
    summary_claims: list[GroundedClaim] = Field(default_factory=list)
    sections: list[GeneratedReportSection]
    key_entities: list[dict[str, JsonValue]]
    key_relationships: list[dict[str, JsonValue]]
    timeline: list[ReportTimelineItemRead]
    contradictions: list[dict[str, JsonValue]]
    limitations: list[str]
    citations: list[CitationRead]


class InvestigationReportRead(InvestigationReportSummaryRead):
    content: ReportContentRead | None
    last_error_message: str | None
