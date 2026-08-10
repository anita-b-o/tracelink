import asyncio
from typing import Protocol
from uuid import UUID, uuid4

from tracelink.domain.enums import FakeResearchMode


class DispatchError(RuntimeError):
    pass


class ResearchTaskDispatcher(Protocol):
    async def dispatch(
        self,
        research_task_id: UUID,
        *,
        mode: FakeResearchMode = FakeResearchMode.SUCCESS,
    ) -> str: ...


class CeleryResearchTaskDispatcher:
    async def dispatch(
        self,
        research_task_id: UUID,
        *,
        mode: FakeResearchMode = FakeResearchMode.SUCCESS,
    ) -> str:
        from tracelink.jobs.research import execute_research_task

        celery_task_id = str(uuid4())
        try:
            await asyncio.to_thread(
                execute_research_task.apply_async,
                args=[str(research_task_id), mode.value],
                task_id=celery_task_id,
            )
        except Exception as exc:
            raise DispatchError("could not publish research task") from exc
        return celery_task_id


def get_research_task_dispatcher() -> ResearchTaskDispatcher:
    return CeleryResearchTaskDispatcher()
