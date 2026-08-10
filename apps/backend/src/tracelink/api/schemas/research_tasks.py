from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tracelink.domain.enums import ResearchTaskStatus, ResearchTaskType


class ResearchTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    investigation_id: UUID
    type: ResearchTaskType
    status: ResearchTaskStatus
    query: str
    source_type: str | None
    attempts: int
    result: dict[str, Any] | None
    last_error_code: str | None
    last_error_message: str | None
    active_celery_task_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
