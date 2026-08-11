from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UrlIngestionCreate(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class SourceSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    publisher: str | None
    url: str
    title: str | None
    published_at: datetime | None
    retrieved_at: datetime
    document_count: int = 0


class DocumentSummaryRead(BaseModel):
    id: UUID
    source: SourceSummaryRead
    mime_type: str
    content_hash: str
    text_preview: str
    content_length: int
    chunk_count: int
    mention_count: int
    evidence_count: int
    created_at: datetime


class DocumentDetailRead(DocumentSummaryRead):
    content_offset: int
    content: str
    has_more: bool
