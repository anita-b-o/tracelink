from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from tracelink.core.config import get_settings
from tracelink.core.logging import configure_logging
from tracelink.domain.models import OutboxEvent
from tracelink.infrastructure.database import close_database, get_session_factory
from tracelink.jobs.celery_app import celery_app
from tracelink.services.outbox import OutboxDispatcher, outbox_payload

logger = logging.getLogger(__name__)


async def dispatch_once() -> int:
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session, session.begin():
        event_ids = await OutboxDispatcher(session, settings).claim()
    for event_id in event_ids:
        try:
            async with factory() as session:
                event = await session.get(OutboxEvent, event_id)
                if event is None:
                    continue
                args, kwargs, queue = outbox_payload(event)
                celery_app.send_task(
                    event.task_name,
                    args=args,
                    kwargs=kwargs,
                    task_id=str(event.id),
                    queue=queue,
                    headers={"request_id": event.request_id} if event.request_id else None,
                )
            async with factory() as session, session.begin():
                await OutboxDispatcher(session, settings).published(event_id)
        except Exception as exc:
            logger.warning("outbox publish failed", extra={"outbox_event_id": str(event_id)})
            async with factory() as session, session.begin():
                await OutboxDispatcher(session, settings).failed(event_id, exc)
    return len(event_ids)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    # This is a container-local liveness marker, not a temporary data or secret file.
    health_path = Path("/tmp/tracelink-outbox-ready")  # nosec B108
    try:
        while not stop.is_set():
            await dispatch_once()
            await asyncio.to_thread(health_path.touch)
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.outbox_poll_interval_seconds)
            except TimeoutError:
                pass
    finally:
        await asyncio.to_thread(health_path.unlink, missing_ok=True)
        await close_database()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
