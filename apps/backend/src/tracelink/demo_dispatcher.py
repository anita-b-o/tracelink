from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

from tracelink.core.config import Settings, get_settings
from tracelink.serverless_dispatcher import (
    SERVERLESS_TASK_HANDLERS,
    ServerlessTaskHandler,
    dispatch_serverless_once,
)

logger = logging.getLogger(__name__)

DemoTaskHandler = ServerlessTaskHandler
DEMO_TASK_HANDLERS = SERVERLESS_TASK_HANDLERS


async def dispatch_demo_once(
    settings: Settings | None = None,
    handlers: Mapping[str, DemoTaskHandler] = DEMO_TASK_HANDLERS,
) -> int:
    configured = settings or get_settings()
    if not configured.demo_mode or configured.app_env != "demo":
        raise RuntimeError("demo dispatcher requires APP_ENV=demo and DEMO_MODE=true")

    return await dispatch_serverless_once(configured, handlers)


async def run_demo_dispatcher(stop: asyncio.Event) -> None:
    settings = get_settings()
    if not settings.demo_mode or settings.app_env != "demo":
        raise RuntimeError("demo dispatcher requires APP_ENV=demo and DEMO_MODE=true")
    while not stop.is_set():
        try:
            await dispatch_demo_once(settings)
        except Exception:
            logger.exception("demo outbox polling failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.outbox_poll_interval_seconds)
        except TimeoutError:
            pass
