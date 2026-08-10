import asyncio
import os
import sys
import time
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import get_settings
from tracelink.domain.enums import EntityType, FakeResearchMode, ResearchTaskStatus
from tracelink.domain.models import (
    Document,
    Entity,
    EntityMention,
    Evidence,
    Relationship,
    RelationshipCandidate,
    Source,
)
from tracelink.jobs.celery_app import celery_app
from tracelink.jobs.research import execute_research_task
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.services.investigation_workflow import InvestigationWorkflowService

pytestmark = [pytest.mark.integration, pytest.mark.celery_smoke, pytest.mark.asyncio]


async def test_real_celery_worker_consumes_research_task(db_session: AsyncSession) -> None:
    suffix = uuid4().hex
    queue = f"tracelink-smoke-{suffix}"
    hostname = f"smoke-{suffix}@localhost"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "celery",
        "--app",
        "tracelink.jobs.celery_app:celery_app",
        "worker",
        "--pool=solo",
        "--concurrency=1",
        f"--queues={queue}",
        f"--hostname={hostname}",
        "--loglevel=WARNING",
        env=os.environ.copy(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ping = await asyncio.to_thread(
                lambda: celery_app.control.inspect(destination=[hostname], timeout=1).ping()
            )
            if ping and hostname in ping:
                break
            if process.returncode is not None:
                output = (await process.stdout.read()).decode() if process.stdout else ""
                pytest.fail(f"Celery worker exited before readiness:\n{output}")
            await asyncio.sleep(0.25)
        else:
            pytest.fail("Celery worker did not become ready")

        investigation = await InvestigationRepository(db_session).create("Smoke", "Query")
        started = await InvestigationWorkflowService(db_session, get_settings()).start(
            investigation.id
        )
        await db_session.commit()
        research_task_id = started.pending_task_ids[0]
        execute_research_task.apply_async(
            args=[str(research_task_id), FakeResearchMode.PIPELINE_SUCCESS.value],
            task_id=f"smoke-job-{suffix}",
            queue=queue,
        )

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            db_session.expire_all()
            task = await ResearchTaskRepository(db_session).get_by_id(research_task_id)
            if task is not None and task.status is ResearchTaskStatus.COMPLETED:
                assert task.attempts == 1
                assert task.result is not None
                break
            await db_session.rollback()
            await asyncio.sleep(0.1)
        else:
            pytest.fail("Celery worker did not complete the research task")

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            await db_session.rollback()
            mention_count = await db_session.scalar(select(func.count()).select_from(EntityMention))
            relationship_count = await db_session.scalar(
                select(func.count()).select_from(Relationship)
            )
            evidence_count = await db_session.scalar(select(func.count()).select_from(Evidence))
            if mention_count and mention_count >= 2 and relationship_count and evidence_count:
                entity_types = set(await db_session.scalars(select(Entity.type)))
                assert {EntityType.PERSON, EntityType.COMPANY} <= entity_types
                assert await db_session.scalar(select(func.count()).select_from(Source)) == 1
                assert await db_session.scalar(select(func.count()).select_from(Document)) == 1
                assert (
                    await db_session.scalar(select(func.count()).select_from(RelationshipCandidate))
                    == 1
                )
                assert relationship_count == 1
                assert evidence_count == 1
                break
            await asyncio.sleep(0.1)
        else:
            output = (await process.stdout.read()).decode() if process.stdout else ""
            pytest.fail(f"Celery worker did not complete relationship pipeline:\n{output}")
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=5)
