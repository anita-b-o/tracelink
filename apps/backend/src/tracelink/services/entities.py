from uuid import UUID

from tracelink.domain.enums import EntityType
from tracelink.domain.models import Entity, EntityAlias, JsonObject
from tracelink.domain.normalization import normalize_entity_name
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
        parts = normalize_entity_name(
            entity_type, require_non_empty(canonical_name, "canonical_name")
        )
        entity = await self.repository.create(
            entity_type=entity_type,
            canonical_name=parts.canonical,
            normalized_name=parts.normalized,
            comparison_key=parts.comparison_key,
            metadata=metadata,
        )
        seen = {parts.comparison_key}
        for alias in aliases or []:
            alias_parts = normalize_entity_name(entity_type, require_non_empty(alias, "alias"))
            if alias_parts.comparison_key in seen:
                raise DomainConflictError("alias duplicates the canonical name or another alias")
            seen.add(alias_parts.comparison_key)
            await self.repository.add_alias(
                entity,
                alias_parts.canonical,
                alias_parts.normalized,
                alias_parts.comparison_key,
            )
        stored = await self.repository.get_by_id(entity.id)
        if stored is None:
            raise RuntimeError("created entity could not be reloaded")
        return stored

    async def add_alias(self, entity_id: UUID, alias: str) -> EntityAlias:
        entity = await self.repository.get_by_id(entity_id)
        if entity is None:
            raise DomainNotFoundError("entity not found")
        parts = normalize_entity_name(entity.type, require_non_empty(alias, "alias"))
        if parts.comparison_key == entity.comparison_key:
            raise DomainConflictError("alias duplicates the canonical name")
        if await self.repository.get_alias(entity_id, parts.comparison_key) is not None:
            raise DomainConflictError("alias already exists for this entity")
        return await self.repository.add_alias(
            entity, parts.canonical, parts.normalized, parts.comparison_key
        )
