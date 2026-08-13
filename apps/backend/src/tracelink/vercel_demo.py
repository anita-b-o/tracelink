from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from tracelink.core.config import Settings
from tracelink.demo_dispatcher import dispatch_demo_once

logger = logging.getLogger(__name__)

DispatchOnce = Callable[[Settings], Awaitable[int]]


def is_dispatch_trigger(method: str, path: str) -> bool:
    if method != "GET":
        return False
    parts = [part for part in path.split("/") if part]
    if len(parts) not in {3, 4} or parts[0] != "api":
        return False

    resource = parts[1]
    if resource == "investigations":
        suffix_allowed = len(parts) == 3 or parts[3] in {"progress", "reports", "tasks"}
    elif resource == "reports":
        suffix_allowed = len(parts) == 3
    else:
        return False
    if not suffix_allowed:
        return False

    try:
        UUID(parts[2])
    except ValueError:
        return False
    return True


class RequestTriggeredOutboxMiddleware(BaseHTTPMiddleware):
    """Advance the durable demo outbox only while a relevant request is alive."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        dispatch_once: DispatchOnce = dispatch_demo_once,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.dispatch_once = dispatch_once

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        enabled = self.settings.demo_mode and self.settings.serverless_runtime
        if enabled and is_dispatch_trigger(request.method, request.url.path):
            try:
                async with asyncio.timeout(self.settings.serverless_dispatch_timeout_seconds):
                    await self.dispatch_once(self.settings)
            except TimeoutError:
                logger.warning("serverless demo outbox dispatch timed out")
            except Exception:
                logger.exception("serverless demo outbox dispatch failed")
        return await call_next(request)
