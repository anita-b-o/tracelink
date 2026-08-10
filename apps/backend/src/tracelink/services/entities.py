from uuid import UUID

from tracelink.domain.enums import EntityType
from tracelink.domain.models import Entity, EntityAlias, JsonObject
from tracelink.domain.normalization import clean_text, normalize_name
from tracelink.domain.validation import require_non_empty
from tracelink.repositories.entities import EntityRepository
from tracelink.services.errors import DomainConflictError, DomainNotFoundError


class EntityService:
    def __init__(self, repository: EntityRepository) -> None:
        self.repository = repository

    async def create(
        self,
        *,
        entity_type: EntityType,
        canonical_name: str,
        aliases: list[str] | None = None,
        metadata: JsonObject | None = None,
    ) -> Entity:
        canonical = require_non_empty(clean_text(canonical_name), "canonical_name")
        normalized = normalize_name(canonical)
        entity = await self.repository.create(
            entity_type=entity_type,
            canonical_name=canonical,
            normalized_name=normalized,
            metadata=metadata,
        )
        seen = {normalized}
        for alias in aliases or []:
            cleaned_alias = require_non_empty(clean_text(alias), "alias")
            normalized_alias = normalize_name(cleaned_alias)
            if normalized_alias in seen:
                raise DomainConflictError("alias duplicates the canonical name or another alias")
            seen.add(normalized_alias)
            await self.repository.add_alias(entity, cleaned_alias, normalized_alias)
        stored = await self.repository.get_by_id(entity.id)
        if stored is None:
            raise RuntimeError("created entity could not be reloaded")
        return stored

    async def add_alias(self, entity_id: UUID, alias: str) -> EntityAlias:
        entity = await self.repository.get_by_id(entity_id)
        if entity is None:
            raise DomainNotFoundError("entity not found")
        cleaned_alias = require_non_empty(clean_text(alias), "alias")
        normalized_alias = normalize_name(cleaned_alias)
        if normalized_alias == entity.normalized_name:
            raise DomainConflictError("alias duplicates the canonical name")
        if await self.repository.get_alias(entity_id, normalized_alias) is not None:
            raise DomainConflictError("alias already exists for this entity")
        return await self.repository.add_alias(entity, cleaned_alias, normalized_alias)
