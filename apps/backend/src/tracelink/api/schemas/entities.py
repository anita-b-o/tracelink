from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from tracelink.domain.enums import EntityType

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
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: EntityType
    canonical_name: str
    normalized_name: str
    metadata: dict[str, JsonValue] = Field(validation_alias="metadata_")
    aliases: list[EntityAliasRead]
    created_at: datetime
    updated_at: datetime
