from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from tracelink.domain.enums import InvestigationStatus

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class InvestigationCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    title: Title
    original_query: Query


class InvestigationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    original_query: str
    status: InvestigationStatus
    created_at: datetime
    updated_at: datetime


class InvestigationProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    pending: int
    running: int
    completed: int
    failed: int
    cancelled: int
    percent: int


class InvestigationCountsRead(BaseModel):
    tasks: int = Field(ge=0)
    entities: int = Field(ge=0)
    relationships: int = Field(ge=0)
    contradictions: int = Field(ge=0)
    sources: int = Field(ge=0)
    documents: int = Field(ge=0)


class InvestigationSummaryRead(InvestigationRead):
    progress: InvestigationProgressRead
    counts: InvestigationCountsRead
