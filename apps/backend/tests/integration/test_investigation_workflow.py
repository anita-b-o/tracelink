import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import get_settings
from tracelink.domain.enums import (
    FakeResearchMode,
    InvestigationStatus,
    ResearchTaskStatus,
)
from tracelink.domain.models import Investigation, ResearchTask
from tracelink.jobs.research import execute_research_task_async
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.services.errors import DomainInvalidTransitionError, DomainRetryLimitError
from tracelink.services.investigation_workflow import InvestigationWorkflowService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def create_and_start(
    session: AsyncSession, query: str = "Investigate ACME"
) -> tuple[Investigation, list[ResearchTask]]:
    investigation = await InvestigationRepository(session).create("ACME", query)
    result = await InvestigationWorkflowService(session, get_settings()).start(investigation.id)
    await session.commit()
    tasks = await ResearchTaskRepository(session).list_by_investigation(investigation.id)
    assert set(result.pending_task_ids) == {task.id for task in tasks}
    return investigation, tasks


async def refresh_investigation(session: AsyncSession, investigation_id: UUID) -> Investigation:
    session.expire_all()
    investigation = await InvestigationRepository(session).get_by_id(investigation_id)
    assert investigation is not None
    return investigation


async def run_task(task: ResearchTask, mode: FakeResearchMode) -> None:
    await execute_research_task_async(task.id, str(uuid4()), mode)


async def test_start_creates_one_idempotent_plan(db_session: AsyncSession) -> None:
    investigation, tasks = await create_and_start(db_session)
    second = await InvestigationWorkflowService(db_session, get_settings()).start(investigation.id)
    await db_session.commit()

    assert len(tasks) == 4
    assert len(second.pending_task_ids) == 4
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ResearchTask)
            .where(ResearchTask.investigation_id == investigation.id)
        )
        == 4
    )


async def test_concurrent_start_does_not_duplicate_plan(db_session: AsyncSession) -> None:
    investigation = await InvestigationRepository(db_session).create("Concurrent", "Query")
    await db_session.commit()
    investigation_id = investigation.id

    async def start_once() -> None:
        from tracelink.infrastructure.database import get_session_factory

        async with get_session_factory()() as session, session.begin():
            await InvestigationWorkflowService(session, get_settings()).start(investigation_id)

    await asyncio.gather(start_once(), start_once())
    db_session.expire_all()
    tasks = await ResearchTaskRepository(db_session).list_by_investigation(investigation_id)
    assert len(tasks) == 4


async def test_all_success_completes_investigation(db_session: AsyncSession) -> None:
    investigation, tasks = await create_and_start(db_session)
    for task in tasks:
        await run_task(task, FakeResearchMode.SUCCESS)

    stored = await refresh_investigation(db_session, investigation.id)
    progress = await InvestigationWorkflowService(db_session, get_settings()).progress(stored.id)
    assert stored.status is InvestigationStatus.COMPLETED
    assert progress.completed == progress.total == 4
    assert progress.percent == 100


async def test_success_and_failure_produces_partial(db_session: AsyncSession) -> None:
    investigation, tasks = await create_and_start(db_session)
    await run_task(tasks[0], FakeResearchMode.ALWAYS_FAIL)
    for task in tasks[1:]:
        await run_task(task, FakeResearchMode.SUCCESS)

    assert (
        await refresh_investigation(db_session, investigation.id)
    ).status is InvestigationStatus.PARTIAL


async def test_all_fail_produces_failed(db_session: AsyncSession) -> None:
    investigation, tasks = await create_and_start(db_session)
    for task in tasks:
        await run_task(task, FakeResearchMode.ALWAYS_FAIL)

    assert (
        await refresh_investigation(db_session, investigation.id)
    ).status is InvestigationStatus.FAILED


async def test_fail_once_retry_then_success(db_session: AsyncSession) -> None:
    investigation, tasks = await create_and_start(db_session)
    failed_task_id = tasks[0].id
    await run_task(tasks[0], FakeResearchMode.FAIL_ONCE)
    for task in tasks[1:]:
        await run_task(task, FakeResearchMode.SUCCESS)

    db_session.expire_all()
    service = InvestigationWorkflowService(db_session, get_settings())
    retried = await service.retry(failed_task_id)
    assert retried.attempts == 1
    assert retried.started_at is not None
    retried_id = retried.id
    await db_session.commit()
    await run_task(retried, FakeResearchMode.FAIL_ONCE)

    stored = await refresh_investigation(db_session, investigation.id)
    stored_task = await ResearchTaskRepository(db_session).get_by_id(retried_id)
    assert stored.status is InvestigationStatus.COMPLETED
    assert stored_task is not None
    assert stored_task.status is ResearchTaskStatus.COMPLETED
    assert stored_task.attempts == 2
    assert stored_task.last_error_code == "FAKE_RESEARCH_FAILED"


async def test_max_attempts_blocks_domain_retry(db_session: AsyncSession) -> None:
    _, tasks = await create_and_start(db_session)
    task = tasks[0]
    task_id = task.id
    for attempt in range(get_settings().research_task_max_attempts):
        await run_task(task, FakeResearchMode.ALWAYS_FAIL)
        db_session.expire_all()
        stored_task = await ResearchTaskRepository(db_session).get_by_id(task_id)
        assert stored_task is not None
        task = stored_task
        if attempt + 1 < get_settings().research_task_max_attempts:
            task = await InvestigationWorkflowService(db_session, get_settings()).retry(task.id)
            await db_session.commit()

    with pytest.raises(DomainRetryLimitError):
        await InvestigationWorkflowService(db_session, get_settings()).retry(task.id)


async def test_cancel_pending_marks_all_tasks_cancelled(db_session: AsyncSession) -> None:
    investigation, _ = await create_and_start(db_session)
    cancelled = await InvestigationWorkflowService(db_session, get_settings()).cancel(
        investigation.id
    )
    await db_session.commit()
    tasks = await ResearchTaskRepository(db_session).list_by_investigation(investigation.id)

    assert cancelled.status is InvestigationStatus.CANCELLED
    assert {task.status for task in tasks} == {ResearchTaskStatus.CANCELLED}
    assert all(task.completed_at is not None for task in tasks)


async def test_late_completion_cannot_overwrite_cancellation(db_session: AsyncSession) -> None:
    investigation, tasks = await create_and_start(db_session)
    task_id = tasks[0].id
    celery_task_id = str(uuid4())
    claimed = await InvestigationWorkflowService(db_session, get_settings()).claim(
        task_id, celery_task_id
    )
    await db_session.commit()
    assert claimed is not None
    await InvestigationWorkflowService(db_session, get_settings()).cancel(investigation.id)
    await db_session.commit()

    await InvestigationWorkflowService(db_session, get_settings()).complete(
        task_id, celery_task_id, {"late": True}
    )
    await db_session.commit()
    stored = await refresh_investigation(db_session, investigation.id)
    stored_task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert stored.status is InvestigationStatus.CANCELLED
    assert stored_task is not None
    assert stored_task.status is ResearchTaskStatus.CANCELLED
    assert stored_task.result is None


async def test_slow_running_task_observes_cooperative_cancellation(
    db_session: AsyncSession,
) -> None:
    from tracelink.infrastructure.database import get_session_factory

    investigation, tasks = await create_and_start(db_session)
    investigation_id = investigation.id
    task_id = tasks[0].id
    execution = asyncio.create_task(
        execute_research_task_async(task_id, "slow-cancellation", FakeResearchMode.SLOW)
    )
    await asyncio.sleep(0.1)
    async with get_session_factory()() as cancellation_session, cancellation_session.begin():
        await InvestigationWorkflowService(cancellation_session, get_settings()).cancel(
            investigation_id
        )
    await execution

    db_session.expire_all()
    stored = await InvestigationRepository(db_session).get_by_id(investigation_id)
    stored_task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert stored is not None
    assert stored.status is InvestigationStatus.CANCELLED
    assert stored_task is not None
    assert stored_task.status is ResearchTaskStatus.CANCELLED
    assert stored_task.result is None


async def test_redelivery_does_not_execute_completed_task_twice(
    db_session: AsyncSession,
) -> None:
    _, tasks = await create_and_start(db_session)
    task_id = tasks[0].id
    celery_task_id = str(uuid4())
    await execute_research_task_async(task_id, celery_task_id, FakeResearchMode.SUCCESS)
    await execute_research_task_async(task_id, celery_task_id, FakeResearchMode.ALWAYS_FAIL)

    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None
    assert task.status is ResearchTaskStatus.COMPLETED
    assert task.attempts == 1
    assert task.last_error_code is None


async def test_timestamps_are_consistent(db_session: AsyncSession) -> None:
    _, tasks = await create_and_start(db_session)
    task_id = tasks[0].id
    await run_task(tasks[0], FakeResearchMode.ALWAYS_FAIL)
    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None
    assert task.started_at is not None
    assert task.completed_at is not None
    assert task.completed_at >= task.started_at


async def test_retry_rejects_non_failed_task(db_session: AsyncSession) -> None:
    _, tasks = await create_and_start(db_session)
    with pytest.raises(DomainInvalidTransitionError, match="only a failed"):
        await InvestigationWorkflowService(db_session, get_settings()).retry(tasks[0].id)
