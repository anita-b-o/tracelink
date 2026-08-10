from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from tracelink.domain.enums import EntityType


class ExtractionContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    investigation_id: UUID
    document_id: UUID
    chunk_index: int = Field(ge=0)


class ExtractedEntityCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: EntityType
    surface_form: str = Field(min_length=1, max_length=500)
    canonical_name_candidate: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=1)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    reasoning_signals: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_offsets(self) -> ExtractedEntityCandidate:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must both be present or absent")
        if self.start_offset is not None and self.end_offset is not None:
            if self.end_offset <= self.start_offset:
                raise ValueError("end_offset must be greater than start_offset")
        if self.type is EntityType.DOCUMENT:
            raise ValueError("DOCUMENT extraction is not enabled in phase 4")
        return self


class EntityExtractionProvider(Protocol):
    name: str

    async def extract(
        self,
        text: str,
        allowed_types: frozenset[EntityType],
        context: ExtractionContext,
    ) -> list[ExtractedEntityCandidate]: ...


class EntityExtractionProviderError(RuntimeError):
    pass
