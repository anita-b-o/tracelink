from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.enums import OutboxStatus, ResearchTaskStatus
from tracelink.domain.models import OutboxEvent
from tracelink.infrastructure.database import get_session_factory
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.serverless_dispatcher import ServerlessTaskHandler, dispatch_serverless_once
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.outbox import OutboxDispatcher, enqueue_task

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def production_serverless_settings() -> Settings:
    return Settings(
        app_env="production",
        serverless_runtime=True,
        cors_allowed_origins="https://web.example",
        allowed_hosts="api.example",
        auth_jwt_secret="a" * 40,
        auth_token_pepper="b" * 40,
        cookie_secure=True,
        registration_enabled=True,
        embedding_provider="openai",
        llm_provider="openai",
        openai_api_key="placeholder-for-validation",
        outbox_batch_size=100,
        outbox_lease_seconds=60,
    )


async def test_production_serverless_dispatches_one_event_per_request(
    db_session: AsyncSession,
) -> None:
    for index in range(4):
        await enqueue_task(db_session, "test.serverless", [index])
    await db_session.commit()

    calls: list[list[Any]] = []

    async def handler(_: OutboxEvent, args: list[Any]) -> None:
        calls.append(args)

    handlers: dict[str, ServerlessTaskHandler] = {"test.serverless": handler}
    settings = production_serverless_settings()

    assert await dispatch_serverless_once(settings, handlers) == 1
    assert calls == [[0]]
    assert await dispatch_serverless_once(settings, handlers) == 1
    assert await dispatch_serverless_once(settings, handlers) == 1
    assert await dispatch_serverless_once(settings, handlers) == 1
    assert calls == [[0], [1], [2], [3]]

    db_session.expire_all()
    events = list(await db_session.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at)))
    assert len(events) == 4
    assert all(event.status is OutboxStatus.PUBLISHED for event in events)
    assert all(event.attempts == 1 for event in events)


async def test_serverless_start_delivery_claims_a_research_task(
    db_session: AsyncSession,
) -> None:
    investigation = await InvestigationRepository(db_session).create(
        "Serverless", "Investigate ACME"
    )
    workflow = InvestigationWorkflowService(db_session, production_serverless_settings())
    started = await workflow.start(investigation.id)
    for task_id in started.pending_task_ids:
        await enqueue_task(db_session, "test.research", [str(task_id), None])
    await db_session.commit()

    async def handler(event: OutboxEvent, args: list[Any]) -> None:
        async with get_session_factory()() as session, session.begin():
            task = await InvestigationWorkflowService(
                session, production_serverless_settings()
            ).claim(UUID(str(args[0])), str(event.id))
            assert task is not None

    assert await dispatch_serverless_once(
        production_serverless_settings(), {"test.research": handler}
    ) == 1
    db_session.expire_all()
    tasks = await ResearchTaskRepository(db_session).list_by_investigation(investigation.id)
    assert len(tasks) == 4
    assert sum(task.attempts for task in tasks) == 1
    assert sum(task.status is ResearchTaskStatus.RUNNING for task in tasks) == 1


async def test_concurrent_serverless_polls_do_not_execute_an_event_twice(
    db_session: AsyncSession,
) -> None:
    for index in range(2):
        await enqueue_task(db_session, "test.serverless", [index])
    await db_session.commit()

    calls: list[int] = []

    async def handler(_: OutboxEvent, args: list[Any]) -> None:
        calls.append(int(args[0]))

    handlers: dict[str, ServerlessTaskHandler] = {"test.serverless": handler}
    await asyncio.gather(
        dispatch_serverless_once(production_serverless_settings(), handlers),
        dispatch_serverless_once(production_serverless_settings(), handlers),
    )

    assert sorted(calls) == [0, 1]


async def test_expired_serverless_lease_is_recovered(
    db_session: AsyncSession,
) -> None:
    event = await enqueue_task(db_session, "test.serverless", ["recovered"])
    event_id = event.id
    await db_session.commit()

    settings = production_serverless_settings()
    assert await OutboxDispatcher(db_session, settings).claim(limit=1) == [event_id]
    event.locked_at = datetime.now(UTC) - timedelta(seconds=settings.outbox_lease_seconds + 1)
    await db_session.commit()

    calls: list[str] = []

    async def handler(_: OutboxEvent, args: list[Any]) -> None:
        calls.append(str(args[0]))

    assert await dispatch_serverless_once(settings, {"test.serverless": handler}) == 1
    db_session.expire_all()
    recovered = await db_session.get(OutboxEvent, event_id)
    assert recovered is not None
    assert recovered.status is OutboxStatus.PUBLISHED
    assert recovered.attempts == 2
    assert calls == ["recovered"]
