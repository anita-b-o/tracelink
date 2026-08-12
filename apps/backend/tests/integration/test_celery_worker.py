import asyncio
import os
import sys
import time
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import get_settings
from tracelink.domain.enums import (
    EntityType,
    FakeResearchMode,
    InvestigationReportStatus,
    InvestigationReportType,
    ResearchTaskStatus,
)
from tracelink.domain.models import (
    Document,
    EmbeddingRecord,
    Entity,
    EntityMention,
    Evidence,
    InvestigationReport,
    Relationship,
    RelationshipCandidate,
    RetrievalChunk,
    Source,
)
from tracelink.infrastructure.database import get_session
from tracelink.jobs.celery_app import celery_app
from tracelink.jobs.reports import generate_investigation_report
from tracelink.jobs.research import execute_research_task
from tracelink.main import app
from tracelink.outbox_dispatcher import dispatch_once
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.services.embedding_providers import FakeEmbeddingProvider
from tracelink.services.grounded_reports import InvestigationReportService
from tracelink.services.hybrid_retrieval import HybridRetriever
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.llm_providers import FakeLLMProvider

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
        investigation_id = investigation.id
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
            await dispatch_once()
            await db_session.rollback()
            mention_count = await db_session.scalar(select(func.count()).select_from(EntityMention))
            relationship_count = await db_session.scalar(
                select(func.count()).select_from(Relationship)
            )
            evidence_count = await db_session.scalar(select(func.count()).select_from(Evidence))
            chunk_count = await db_session.scalar(select(func.count()).select_from(RetrievalChunk))
            embedding_count = await db_session.scalar(
                select(func.count()).select_from(EmbeddingRecord)
            )
            if (
                mention_count
                and mention_count >= 2
                and relationship_count
                and evidence_count
                and chunk_count
                and embedding_count
            ):
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
                assert chunk_count >= 1
                assert embedding_count == chunk_count
                break
            await asyncio.sleep(0.1)
        else:
            output = (await process.stdout.read()).decode() if process.stdout else ""
            pytest.fail(f"Celery worker did not complete relationship pipeline:\n{output}")

        async def session_override():  # type: ignore[no-untyped-def]
            yield db_session

        app.dependency_overrides[get_session] = session_override
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                search_response = await client.post(
                    f"/api/investigations/{investigation_id}/search",
                    json={"query": "Juan Pérez director ACME", "top_k": 5},
                )
            assert search_response.status_code == 200, search_response.text
            assert search_response.json()
        finally:
            app.dependency_overrides.clear()

        settings = get_settings()
        report = await InvestigationReportService(
            db_session,
            settings,
            FakeLLMProvider(),
            HybridRetriever(db_session, settings, FakeEmbeddingProvider()),
        ).request(
            investigation_id,
            InvestigationReportType.EXECUTIVE_SUMMARY,
            None,
        )
        report_id = report.id
        await db_session.commit()
        generate_investigation_report.apply_async(args=[str(report_id)], queue=queue)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            await db_session.rollback()
            db_session.expire_all()
            refreshed = await db_session.get(InvestigationReport, report_id)
            if refreshed is not None and refreshed.status is InvestigationReportStatus.COMPLETED:
                assert refreshed.content is not None
                assert refreshed.content["citations"]
                break
            await asyncio.sleep(0.1)
        else:
            await db_session.rollback()
            db_session.expire_all()
            refreshed = await db_session.get(InvestigationReport, report_id)
            detail = (
                f"status={refreshed.status.value} error={refreshed.last_error_message}"
                if refreshed is not None
                else "report missing"
            )
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=10)
            output = (await process.stdout.read()).decode() if process.stdout else ""
            pytest.fail(f"Celery worker did not complete grounded report: {detail}\n{output}")
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=5)
