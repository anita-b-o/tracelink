from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.core.logging import request_id_context
from tracelink.domain.enums import OutboxStatus
from tracelink.domain.models import JsonObject, OutboxEvent


async def enqueue_task(
    session: AsyncSession,
    task_name: str,
    args: list[Any],
    *,
    kwargs: JsonObject | None = None,
    queue: str | None = None,
    request_id: str | None = None,
) -> OutboxEvent:
    payload: JsonObject = {"args": args, "kwargs": kwargs or {}}
    if queue:
        payload["queue"] = queue
    event = OutboxEvent(
        task_name=task_name,
        payload=payload,
        request_id=request_id or request_id_context.get(),
    )
    session.add(event)
    await session.flush()
    return event


class OutboxDispatcher:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def claim(self) -> list[UUID]:
        now = datetime.now(UTC)
        lease_cutoff = now - timedelta(seconds=self.settings.outbox_lease_seconds)
        events = list(
            await self.session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.attempts < self.settings.outbox_max_attempts,
                    OutboxEvent.next_attempt_at <= now,
                    or_(
                        OutboxEvent.status == OutboxStatus.PENDING,
                        OutboxEvent.status == OutboxStatus.FAILED,
                        (
                            (OutboxEvent.status == OutboxStatus.PUBLISHING)
                            & (OutboxEvent.locked_at < lease_cutoff)
                        ),
                    ),
                )
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(self.settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            event.status = OutboxStatus.PUBLISHING
            event.locked_at = now
            event.attempts += 1
        await self.session.flush()
        return [event.id for event in events]

    async def published(self, event_id: UUID) -> None:
        event = await self.session.get(OutboxEvent, event_id, with_for_update=True)
        if event is None:
            return
        event.status = OutboxStatus.PUBLISHED
        event.published_at = datetime.now(UTC)
        event.locked_at = None
        event.last_error = None
        await self.session.flush()

    async def failed(self, event_id: UUID, error: Exception) -> None:
        event = await self.session.get(OutboxEvent, event_id, with_for_update=True)
        if event is None:
            return
        event.status = OutboxStatus.FAILED
        event.locked_at = None
        event.last_error = type(error).__name__[:500]
        delay = min(2 ** min(event.attempts, 8), 300)
        event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        await self.session.flush()

    async def cleanup(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.outbox_retention_days)
        result = await self.session.execute(
            delete(OutboxEvent).where(
                OutboxEvent.status == OutboxStatus.PUBLISHED,
                OutboxEvent.published_at < cutoff,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)


def outbox_payload(event: OutboxEvent) -> tuple[list[Any], dict[str, Any], str | None]:
    raw_args = event.payload.get("args", [])
    raw_kwargs = event.payload.get("kwargs", {})
    raw_queue = event.payload.get("queue")
    args = list(raw_args) if isinstance(raw_args, list) else []
    kwargs = dict(raw_kwargs) if isinstance(raw_kwargs, dict) else {}
    queue = str(raw_queue) if raw_queue else None
    return args, kwargs, queue
