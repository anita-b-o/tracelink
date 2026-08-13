from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.core.logging import request_id_context
from tracelink.demo_dispatcher import DEMO_TASK_HANDLERS, DemoTaskHandler, dispatch_demo_once
from tracelink.domain.enums import OutboxStatus
from tracelink.domain.models import OutboxEvent
from tracelink.services.outbox import enqueue_task

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def demo_settings() -> Settings:
    return Settings(
        app_env="demo",
        demo_mode=True,
        cors_allowed_origins="https://tracelink-demo-web.onrender.com",
        allowed_hosts="tracelink-demo-api.onrender.com",
        auth_jwt_secret="a" * 40,
        auth_token_pepper="b" * 40,
        cookie_secure=True,
        registration_enabled=True,
        embedding_provider="openai",
        llm_provider="openai",
        openai_api_key="placeholder-for-validation",
        outbox_batch_size=1,
        outbox_max_attempts=3,
        outbox_lease_seconds=360,
    )


async def test_demo_dispatcher_publishes_once_and_preserves_request_id(
    db_session: AsyncSession,
) -> None:
    calls: list[tuple[str, list[Any], str | None]] = []

    async def handler(event: OutboxEvent, args: list[Any]) -> None:
        calls.append((str(event.id), args, request_id_context.get()))

    event = await enqueue_task(
        db_session,
        "tracelink.execute_research_task",
        ["task-id", None],
        request_id="demo-request",
    )
    event_id = event.id
    await db_session.commit()

    handlers: dict[str, DemoTaskHandler] = {
        "tracelink.execute_research_task": handler,
    }
    assert await dispatch_demo_once(demo_settings(), handlers) == 1
    assert await dispatch_demo_once(demo_settings(), handlers) == 0

    db_session.expire_all()
    stored = await db_session.get(OutboxEvent, event_id)
    assert stored is not None
    assert stored.status is OutboxStatus.PUBLISHED
    assert stored.attempts == 1
    assert stored.published_at is not None
    assert calls == [(str(event_id), ["task-id", None], "demo-request")]


async def test_demo_dispatcher_retries_failed_or_expired_leased_event(
    db_session: AsyncSession,
) -> None:
    should_fail = True
    calls = 0

    async def handler(_: OutboxEvent, __: list[Any]) -> None:
        nonlocal calls
        calls += 1
        if should_fail:
            raise RuntimeError("transient demo failure")

    event = await enqueue_task(
        db_session,
        "tracelink.process_document_entities",
        ["investigation-id", "document-id"],
    )
    event_id = event.id
    await db_session.commit()
    handlers: dict[str, DemoTaskHandler] = {
        "tracelink.process_document_entities": handler,
    }

    assert await dispatch_demo_once(demo_settings(), handlers) == 1
    db_session.expire_all()
    failed = await db_session.get(OutboxEvent, event_id)
    assert failed is not None
    assert failed.status is OutboxStatus.FAILED
    assert failed.attempts == 1
    assert failed.last_error == "RuntimeError"

    should_fail = False
    failed.status = OutboxStatus.PUBLISHING
    failed.locked_at = datetime.now(UTC) - timedelta(seconds=361)
    failed.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert await dispatch_demo_once(demo_settings(), handlers) == 1
    db_session.expire_all()
    published = await db_session.get(OutboxEvent, event_id)
    assert published is not None
    assert published.status is OutboxStatus.PUBLISHED
    assert published.attempts == 2
    assert calls == 2


async def test_demo_dispatcher_rejects_tasks_outside_allowlist(
    db_session: AsyncSession,
) -> None:
    event = await enqueue_task(db_session, "tracelink.not_allowed", [])
    event_id = event.id
    await db_session.commit()

    assert set(DEMO_TASK_HANDLERS) == {
        "tracelink.execute_research_task",
        "tracelink.process_document_entities",
        "tracelink.process_document_relationships",
        "tracelink.index_document_for_retrieval",
        "tracelink.generate_investigation_report",
    }
    assert await dispatch_demo_once(demo_settings()) == 1

    db_session.expire_all()
    stored = await db_session.get(OutboxEvent, event_id)
    assert stored is not None
    assert stored.status is OutboxStatus.FAILED
    assert stored.last_error == "ValueError"


async def test_demo_dispatcher_refuses_non_demo_configuration() -> None:
    with pytest.raises(RuntimeError, match="requires APP_ENV=demo"):
        await dispatch_demo_once(Settings(app_env="test"), {})
