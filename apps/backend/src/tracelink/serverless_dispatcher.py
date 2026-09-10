from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.exc import OperationalError

from tracelink.core.config import Settings
from tracelink.core.logging import request_id_context
from tracelink.domain.models import OutboxEvent
from tracelink.infrastructure.database import get_session_factory
from tracelink.jobs.entities import process_document_entities_async
from tracelink.jobs.rag import index_document_for_retrieval_async
from tracelink.jobs.relationships import process_document_relationships_async
from tracelink.jobs.reports import (
    fail_investigation_report_async,
    generate_investigation_report_async,
)
from tracelink.jobs.research import execute_research_task_async
from tracelink.services.llm_providers import TransientLLMProviderError
from tracelink.services.outbox import OutboxDispatcher, outbox_payload

logger = logging.getLogger(__name__)

ServerlessTaskHandler = Callable[[OutboxEvent, list[Any]], Awaitable[None]]


def _uuid_arg(args: list[Any], index: int) -> UUID:
    try:
        return UUID(str(args[index]))
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid UUID argument at index {index}") from exc


def _require_arg_count(args: list[Any], expected: int) -> None:
    if len(args) != expected:
        raise ValueError(f"expected {expected} task arguments, received {len(args)}")


async def _execute_research(event: OutboxEvent, args: list[Any]) -> None:
    _require_arg_count(args, 2)
    if args[1] is not None:
        raise ValueError("fake research modes are forbidden in serverless dispatch")
    await execute_research_task_async(_uuid_arg(args, 0), str(event.id), None)


async def _process_entities(_: OutboxEvent, args: list[Any]) -> None:
    _require_arg_count(args, 2)
    await process_document_entities_async(_uuid_arg(args, 0), _uuid_arg(args, 1))


async def _process_relationships(_: OutboxEvent, args: list[Any]) -> None:
    _require_arg_count(args, 2)
    await process_document_relationships_async(_uuid_arg(args, 0), _uuid_arg(args, 1))


async def _index_document(_: OutboxEvent, args: list[Any]) -> None:
    _require_arg_count(args, 2)
    await index_document_for_retrieval_async(_uuid_arg(args, 0), _uuid_arg(args, 1))


async def _generate_report(event: OutboxEvent, args: list[Any]) -> None:
    _require_arg_count(args, 1)
    report_id = _uuid_arg(args, 0)
    try:
        await generate_investigation_report_async(report_id, str(event.id))
    except (OperationalError, TransientLLMProviderError):
        raise
    except Exception as exc:
        logger.exception("serverless report generation failed", extra={"report_id": str(report_id)})
        await fail_investigation_report_async(report_id, "REPORT_GENERATION_FAILED", str(exc)[:500])


SERVERLESS_TASK_HANDLERS: Mapping[str, ServerlessTaskHandler] = {
    "tracelink.execute_research_task": _execute_research,
    "tracelink.process_document_entities": _process_entities,
    "tracelink.process_document_relationships": _process_relationships,
    "tracelink.index_document_for_retrieval": _index_document,
    "tracelink.generate_investigation_report": _generate_report,
}


async def dispatch_serverless_once(
    settings: Settings,
    handlers: Mapping[str, ServerlessTaskHandler] = SERVERLESS_TASK_HANDLERS,
) -> int:
    """Claim and execute at most one durable outbox event in the active request."""
    factory = get_session_factory()
    async with factory() as session, session.begin():
        event_ids = await OutboxDispatcher(session, settings).claim(limit=1)

    for event_id in event_ids:
        task_name = "unknown"
        try:
            async with factory() as session:
                event = await session.get(OutboxEvent, event_id)
                if event is None:
                    continue
                task_name = event.task_name
                args, kwargs, queue = outbox_payload(event)
                if kwargs or queue is not None:
                    raise ValueError("serverless tasks do not accept keyword arguments or queues")
                handler = handlers.get(event.task_name)
                if handler is None:
                    raise ValueError(f"task is not allowed in serverless mode: {event.task_name}")
                request_token = request_id_context.set(event.request_id)
                try:
                    await handler(event, args)
                finally:
                    request_id_context.reset(request_token)
            async with factory() as session, session.begin():
                await OutboxDispatcher(session, settings).published(event_id)
        except Exception as exc:
            logger.warning(
                "serverless outbox execution failed",
                extra={"outbox_event_id": str(event_id), "task_name": task_name},
            )
            async with factory() as session, session.begin():
                await OutboxDispatcher(session, settings).failed(event_id, exc)
    return len(event_ids)


async def dispatch_serverless_safely(
    settings: Settings,
    dispatch_once: Callable[[Settings], Awaitable[int]] = dispatch_serverless_once,
) -> int:
    """Bound serverless work to the live request without background execution.

    A timeout cancels the handler after the claim transaction has committed. The
    event consequently remains ``PUBLISHING`` and becomes eligible again once its
    durable lease expires.
    """
    try:
        async with asyncio.timeout(settings.serverless_dispatch_timeout_seconds):
            return await dispatch_once(settings)
    except TimeoutError:
        logger.warning("serverless outbox dispatch timed out")
    except Exception:
        logger.exception("serverless outbox dispatch failed")
    return 0
