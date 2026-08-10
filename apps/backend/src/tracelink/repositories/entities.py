from __future__ import annotations

import builtins
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracelink.domain.enums import EntityType
from tracelink.domain.models import Entity, EntityAlias, JsonObject


class EntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        entity_type: EntityType,
        canonical_name: str,
        normalized_name: str,
        metadata: JsonObject | None = None,
    ) -> Entity:
        entity = Entity(
            type=entity_type,
            canonical_name=canonical_name,
            normalized_name=normalized_name,
            metadata_=metadata or {},
        )
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def get_by_id(self, entity_id: UUID) -> Entity | None:
        return cast(
            Entity | None,
            await self.session.scalar(
                select(Entity).options(selectinload(Entity.aliases)).where(Entity.id == entity_id)
            ),
        )

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Entity]:
        result = await self.session.scalars(
            select(Entity)
            .options(selectinload(Entity.aliases))
            .order_by(Entity.created_at.desc(), Entity.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def find_by_normalized_name(self, normalized_name: str) -> builtins.list[Entity]:
        result = await self.session.scalars(
            select(Entity)
            .options(selectinload(Entity.aliases))
            .where(Entity.normalized_name == normalized_name)
            .order_by(Entity.created_at, Entity.id)
        )
        return list(result)

    async def find_by_alias(self, normalized_alias: str) -> builtins.list[Entity]:
        result = await self.session.scalars(
            select(Entity)
            .join(EntityAlias)
            .options(selectinload(Entity.aliases))
            .where(EntityAlias.normalized_alias == normalized_alias)
            .order_by(Entity.created_at, Entity.id)
        )
        return list(result.unique())

    async def get_alias(self, entity_id: UUID, normalized_alias: str) -> EntityAlias | None:
        return cast(
            EntityAlias | None,
            await self.session.scalar(
                select(EntityAlias).where(
                    EntityAlias.entity_id == entity_id,
                    EntityAlias.normalized_alias == normalized_alias,
                )
            ),
        )

    async def add_alias(self, entity: Entity, alias: str, normalized_alias: str) -> EntityAlias:
        entity_alias = EntityAlias(
            entity_id=entity.id,
            alias=alias,
            normalized_alias=normalized_alias,
        )
        self.session.add(entity_alias)
        await self.session.flush()
        await self.session.refresh(entity_alias)
        return entity_alias

    async def update(
        self,
        entity: Entity,
        *,
        canonical_name: str,
        normalized_name: str,
        metadata: JsonObject | None = None,
    ) -> Entity:
        entity.canonical_name = canonical_name
        entity.normalized_name = normalized_name
        if metadata is not None:
            entity.metadata_ = metadata
        await self.session.flush()
        await self.session.refresh(entity)
        return entity
