from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from tracelink.domain.enums import ResearchTaskType

Metadata = dict[str, Any]


class ConnectorSearchResult(BaseModel):
    external_id: str | None = None
    url: str
    title: str | None = None
    snippet: str | None = None
    published_at: datetime | None = None
    rank: int | None = Field(default=None, ge=1)
    metadata: Metadata = Field(default_factory=dict)


class ConnectorFetchResult(BaseModel):
    url: str
    status_code: int
    content_type: str
    text: str
    retrieved_at: datetime
    metadata: Metadata = Field(default_factory=dict)
    cache_hit: bool = False
    retry_count: int = 0


class ExtractedHtml(BaseModel):
    title: str | None = None
    visible_text: str
    canonical_url: str | None = None
    description: str | None = None
    language: str | None = None
    published_at: datetime | None = None
    outgoing_links: list[str] = Field(default_factory=list)
    metadata: Metadata = Field(default_factory=dict)


class SourceArtifact(BaseModel):
    source_type: str
    url: str
    normalized_url: str
    publisher: str | None = None
    title: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    metadata: Metadata = Field(default_factory=dict)


class DocumentArtifact(BaseModel):
    source_normalized_url: str
    mime_type: str
    raw_text: str
    metadata: Metadata = Field(default_factory=dict)


class ConnectorOutput(BaseModel):
    connector: str
    status: Literal["success", "skipped"] = "success"
    sources: list[SourceArtifact] = Field(default_factory=list)
    documents: list[DocumentArtifact] = Field(default_factory=list)
    result_count: int = Field(default=0, ge=0)
    metadata: Metadata = Field(default_factory=dict)


class ResearchTaskResult(BaseModel):
    connector: str
    status: Literal["success", "skipped", "failed"]
    source_ids: list[UUID] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
    result_count: int = Field(default=0, ge=0)
    metadata: Metadata = Field(default_factory=dict)


class ConnectorContext(BaseModel):
    investigation_id: UUID
    research_task_id: UUID | None = None
    task_type: ResearchTaskType | None = None
