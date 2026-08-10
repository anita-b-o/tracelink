from tracelink.domain.enums import ResearchTaskType
from tracelink.domain.models import Investigation, ResearchTask
from tracelink.repositories.research_tasks import ResearchTaskRepository

RESEARCH_PLAN = (
    ResearchTaskType.IDENTIFY_ENTITY,
    ResearchTaskType.WEB_SEARCH,
    ResearchTaskType.DOMAIN_LOOKUP,
    ResearchTaskType.PUBLIC_MENTIONS,
)


class ResearchPlanner:
    def __init__(self, repository: ResearchTaskRepository) -> None:
        self.repository = repository

    async def plan(self, investigation: Investigation) -> list[ResearchTask]:
        await self.repository.create_plan_items(
            investigation_id=investigation.id,
            query=investigation.original_query,
            task_types=RESEARCH_PLAN,
        )
        return await self.repository.list_by_investigation(investigation.id)
