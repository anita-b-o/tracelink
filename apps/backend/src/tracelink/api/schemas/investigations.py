from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from tracelink.domain.enums import InvestigationStatus

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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
