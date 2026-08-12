from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import FakeResearchMode
from tracelink.domain.models import OutboxEvent
from tracelink.infrastructure.database import get_session
from tracelink.jobs.research import execute_research_task_async
from tracelink.main import app

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_workflow_api_contracts(db_session: AsyncSession) -> None:
    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/investigations",
                json={"title": "Workflow", "original_query": "Investigate ACME"},
            )
            investigation_id = created.json()["id"]

            started = await client.post(f"/api/investigations/{investigation_id}/start")
            assert started.status_code == 202
            assert started.json()["status"] == "PENDING"
            assert await db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 4

            repeated = await client.post(f"/api/investigations/{investigation_id}/start")
            assert repeated.status_code == 202
            assert await db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 8

            tasks_response = await client.get(f"/api/investigations/{investigation_id}/tasks")
            assert tasks_response.status_code == 200
            tasks = tasks_response.json()
            assert len(tasks) == 4

            progress = await client.get(f"/api/investigations/{investigation_id}/progress")
            assert progress.json() == {
                "total": 4,
                "pending": 4,
                "running": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
                "percent": 0,
            }

            detail = await client.get(f"/api/research-tasks/{tasks[0]['id']}")
            assert detail.status_code == 200
            assert detail.json()["type"] in {
                "IDENTIFY_ENTITY",
                "WEB_SEARCH",
                "DOMAIN_LOOKUP",
                "PUBLIC_MENTIONS",
            }

            cancelled = await client.post(f"/api/investigations/{investigation_id}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "CANCELLED"
            assert (
                await client.post(f"/api/investigations/{investigation_id}/cancel")
            ).status_code == 200
            assert (
                await client.post(f"/api/investigations/{investigation_id}/start")
            ).status_code == 409
    finally:
        app.dependency_overrides.clear()


async def test_retry_endpoint_dispatches_failed_task(db_session: AsyncSession) -> None:
    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/investigations",
                json={"title": "Retry", "original_query": "Investigate ACME"},
            )
            investigation_id = created.json()["id"]
            await client.post(f"/api/investigations/{investigation_id}/start")
            tasks = (await client.get(f"/api/investigations/{investigation_id}/tasks")).json()
            failed_id = UUID(tasks[0]["id"])
            await execute_research_task_async(
                failed_id, "api-failure", FakeResearchMode.ALWAYS_FAIL
            )
            db_session.expire_all()

            retried = await client.post(f"/api/research-tasks/{failed_id}/retry")
            assert retried.status_code == 202
            assert retried.json()["status"] == "PENDING"
            assert retried.json()["attempts"] == 1
            event = await db_session.scalar(
                select(OutboxEvent).order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
            )
            assert event is not None
            assert event.payload["args"][0] == str(failed_id)
            assert (await client.post(f"/api/research-tasks/{failed_id}/retry")).status_code == 409
    finally:
        app.dependency_overrides.clear()
