from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.connectors.models import ConnectorOutput, ResearchTaskResult
from tracelink.core.config import Settings
from tracelink.domain.enums import InvestigationStatus, ResearchTaskStatus
from tracelink.domain.models import Investigation, JsonObject, ResearchTask
from tracelink.domain.workflow import (
    InvestigationProgress,
    aggregate_investigation_status,
    calculate_progress,
    transition_investigation,
    transition_research_task,
)
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.services.errors import (
    DomainInvalidTransitionError,
    DomainNotFoundError,
    DomainRetryLimitError,
)
from tracelink.services.research_artifacts import ResearchArtifactService
from tracelink.services.research_planner import ResearchPlanner


@dataclass(frozen=True, slots=True)
class StartResult:
    investigation: Investigation
    pending_task_ids: tuple[UUID, ...]


class InvestigationWorkflowService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.investigations = InvestigationRepository(session)
        self.research_tasks = ResearchTaskRepository(session)

    async def start(self, investigation_id: UUID) -> StartResult:
        investigation = await self.investigations.get_by_id_for_update(investigation_id)
        if investigation is None:
            raise DomainNotFoundError("investigation not found")
        if investigation.status is InvestigationStatus.DRAFT:
            transition_investigation(investigation, InvestigationStatus.PENDING)
        elif investigation.status not in {
            InvestigationStatus.PENDING,
            InvestigationStatus.RUNNING,
        }:
            raise DomainInvalidTransitionError(
                f"investigation in {investigation.status.value} cannot be started"
            )

        tasks = await ResearchPlanner(self.research_tasks).plan(investigation)
        await self.session.flush()
        return StartResult(
            investigation=investigation,
            pending_task_ids=tuple(
                task.id for task in tasks if task.status is ResearchTaskStatus.PENDING
            ),
        )

    async def cancel(self, investigation_id: UUID) -> Investigation:
        investigation = await self.investigations.get_by_id_for_update(investigation_id)
        if investigation is None:
            raise DomainNotFoundError("investigation not found")
        if investigation.status is InvestigationStatus.CANCELLED:
            return investigation
        if investigation.status not in {
            InvestigationStatus.DRAFT,
            InvestigationStatus.PENDING,
            InvestigationStatus.RUNNING,
        }:
            raise DomainInvalidTransitionError(
                f"investigation in {investigation.status.value} cannot be cancelled"
            )

        transition_investigation(investigation, InvestigationStatus.CANCELLED)
        tasks = await self.research_tasks.list_by_investigation_for_update(investigation.id)
        for task in tasks:
            if task.status is ResearchTaskStatus.PENDING:
                transition_research_task(task, ResearchTaskStatus.CANCELLED)
        await self.session.flush()
        return investigation

    async def list_tasks(self, investigation_id: UUID) -> list[ResearchTask]:
        if await self.investigations.get_by_id(investigation_id) is None:
            raise DomainNotFoundError("investigation not found")
        return await self.research_tasks.list_by_investigation(investigation_id)

    async def progress(self, investigation_id: UUID) -> InvestigationProgress:
        return calculate_progress(await self.list_tasks(investigation_id))

    async def retry(self, research_task_id: UUID) -> ResearchTask:
        task_reference = await self.research_tasks.get_by_id(research_task_id)
        if task_reference is None:
            raise DomainNotFoundError("research task not found")
        investigation = await self.investigations.get_by_id_for_update(
            task_reference.investigation_id
        )
        if investigation is None:
            raise DomainNotFoundError("investigation not found")
        task = await self.research_tasks.get_by_id_for_update(research_task_id)
        if task is None:
            raise DomainNotFoundError("research task not found")
        if investigation.status in {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.CANCELLED,
        }:
            raise DomainInvalidTransitionError(
                f"research task cannot be retried while investigation is "
                f"{investigation.status.value}"
            )
        if task.status is not ResearchTaskStatus.FAILED:
            raise DomainInvalidTransitionError("only a failed research task can be retried")
        if task.attempts >= self.settings.research_task_max_attempts:
            raise DomainRetryLimitError(
                f"research task reached the maximum of "
                f"{self.settings.research_task_max_attempts} attempts"
            )

        transition_research_task(task, ResearchTaskStatus.PENDING, explicit_retry=True)
        if investigation.status in {
            InvestigationStatus.FAILED,
            InvestigationStatus.PARTIAL,
        }:
            transition_investigation(
                investigation, InvestigationStatus.PENDING, explicit_retry=True
            )
        await self.session.flush()
        return task

    async def claim(self, research_task_id: UUID, celery_task_id: str) -> ResearchTask | None:
        task_reference = await self.research_tasks.get_by_id(research_task_id)
        if task_reference is None:
            return None
        investigation = await self.investigations.get_by_id_for_update(
            task_reference.investigation_id
        )
        if investigation is None:
            return None
        task = await self.research_tasks.get_by_id_for_update(research_task_id)
        if task is None:
            return None

        if investigation.status is InvestigationStatus.CANCELLED:
            if task.status in {ResearchTaskStatus.PENDING, ResearchTaskStatus.RUNNING}:
                transition_research_task(task, ResearchTaskStatus.CANCELLED)
                await self.session.flush()
            return None
        if task.status in {
            ResearchTaskStatus.COMPLETED,
            ResearchTaskStatus.FAILED,
            ResearchTaskStatus.CANCELLED,
        }:
            return None
        if task.status is ResearchTaskStatus.RUNNING:
            return task if task.active_celery_task_id == celery_task_id else None
        if task.attempts >= self.settings.research_task_max_attempts:
            return None

        transition_research_task(task, ResearchTaskStatus.RUNNING, celery_task_id=celery_task_id)
        if investigation.status is InvestigationStatus.PENDING:
            transition_investigation(investigation, InvestigationStatus.RUNNING)
        await self.session.flush()
        return task

    async def is_cancelled(self, investigation_id: UUID) -> bool:
        investigation = await self.investigations.get_by_id(investigation_id)
        return investigation is None or investigation.status is InvestigationStatus.CANCELLED

    async def complete(
        self, research_task_id: UUID, celery_task_id: str, result: JsonObject
    ) -> bool:
        locked = await self._lock_aggregate(research_task_id)
        if locked is None:
            return False
        investigation, task, tasks = locked
        if investigation.status is InvestigationStatus.CANCELLED:
            if task.status is ResearchTaskStatus.RUNNING:
                transition_research_task(task, ResearchTaskStatus.CANCELLED)
            await self.session.flush()
            return False
        if (
            task.status is not ResearchTaskStatus.RUNNING
            or task.active_celery_task_id != celery_task_id
        ):
            return False
        transition_research_task(task, ResearchTaskStatus.COMPLETED)
        task.result = result
        self._recalculate(investigation, tasks)
        await self.session.flush()
        return True

    async def complete_with_output(
        self,
        research_task_id: UUID,
        celery_task_id: str,
        output: ConnectorOutput,
    ) -> ResearchTaskResult | None:
        locked = await self._lock_aggregate(research_task_id)
        if locked is None:
            return None
        investigation, task, tasks = locked
        if investigation.status is InvestigationStatus.CANCELLED:
            if task.status is ResearchTaskStatus.RUNNING:
                transition_research_task(task, ResearchTaskStatus.CANCELLED)
            await self.session.flush()
            return None
        if (
            task.status is not ResearchTaskStatus.RUNNING
            or task.active_celery_task_id != celery_task_id
        ):
            return None
        result = await ResearchArtifactService(self.session).persist(investigation.id, output)
        transition_research_task(task, ResearchTaskStatus.COMPLETED)
        task.result = result.model_dump(mode="json")
        self._recalculate(investigation, tasks)
        await self.session.flush()
        return result

    async def fail(
        self,
        research_task_id: UUID,
        celery_task_id: str,
        *,
        error_code: str,
        error_message: str,
        failure_result: ResearchTaskResult | None = None,
    ) -> None:
        locked = await self._lock_aggregate(research_task_id)
        if locked is None:
            return
        investigation, task, tasks = locked
        if investigation.status is InvestigationStatus.CANCELLED:
            if task.status is ResearchTaskStatus.RUNNING:
                transition_research_task(task, ResearchTaskStatus.CANCELLED)
            await self.session.flush()
            return
        if (
            task.status is not ResearchTaskStatus.RUNNING
            or task.active_celery_task_id != celery_task_id
        ):
            return
        transition_research_task(task, ResearchTaskStatus.FAILED)
        task.last_error_code = error_code
        task.last_error_message = error_message
        if failure_result is not None:
            task.result = failure_result.model_dump(mode="json")
        self._recalculate(investigation, tasks)
        await self.session.flush()

    async def acknowledge_cancellation(self, research_task_id: UUID, celery_task_id: str) -> None:
        locked = await self._lock_aggregate(research_task_id)
        if locked is None:
            return
        _, task, _ = locked
        if (
            task.status is ResearchTaskStatus.RUNNING
            and task.active_celery_task_id == celery_task_id
        ):
            transition_research_task(task, ResearchTaskStatus.CANCELLED)
            await self.session.flush()

    async def _lock_aggregate(
        self, research_task_id: UUID
    ) -> tuple[Investigation, ResearchTask, list[ResearchTask]] | None:
        task_reference = await self.research_tasks.get_by_id(research_task_id)
        if task_reference is None:
            return None
        investigation = await self.investigations.get_by_id_for_update(
            task_reference.investigation_id
        )
        if investigation is None:
            return None
        tasks = await self.research_tasks.list_by_investigation_for_update(investigation.id)
        task = next((item for item in tasks if item.id == research_task_id), None)
        if task is None:
            return None
        return investigation, task, tasks

    @staticmethod
    def _recalculate(investigation: Investigation, tasks: list[ResearchTask]) -> None:
        target = aggregate_investigation_status(investigation, tasks)
        if target is not investigation.status:
            transition_investigation(investigation, target)
