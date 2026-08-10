from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import ResearchTaskStatus, ResearchTaskType
from tracelink.domain.models import ResearchTask


class ResearchTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, research_task_id: UUID) -> ResearchTask | None:
        return await self.session.get(ResearchTask, research_task_id)

    async def get_by_id_for_update(self, research_task_id: UUID) -> ResearchTask | None:
        return cast(
            ResearchTask | None,
            await self.session.scalar(
                select(ResearchTask).where(ResearchTask.id == research_task_id).with_for_update()
            ),
        )

    async def list_by_investigation(self, investigation_id: UUID) -> list[ResearchTask]:
        result = await self.session.scalars(
            select(ResearchTask)
            .where(ResearchTask.investigation_id == investigation_id)
            .order_by(ResearchTask.created_at, ResearchTask.type, ResearchTask.id)
        )
        return list(result)

    async def list_by_investigation_for_update(self, investigation_id: UUID) -> list[ResearchTask]:
        result = await self.session.scalars(
            select(ResearchTask)
            .where(ResearchTask.investigation_id == investigation_id)
            .order_by(ResearchTask.created_at, ResearchTask.type, ResearchTask.id)
            .with_for_update()
        )
        return list(result)

    async def create_plan_items(
        self,
        *,
        investigation_id: UUID,
        query: str,
        task_types: Sequence[ResearchTaskType],
    ) -> None:
        if not task_types:
            return
        statement = insert(ResearchTask).values(
            [
                {
                    "investigation_id": investigation_id,
                    "type": task_type,
                    "status": ResearchTaskStatus.PENDING,
                    "query": query,
                    "source_type": None,
                    "attempts": 0,
                }
                for task_type in task_types
            ]
        )
        await self.session.execute(
            statement.on_conflict_do_nothing(
                index_elements=[ResearchTask.investigation_id, ResearchTask.type]
            )
        )
        await self.session.flush()
