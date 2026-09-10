from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from tracelink.core.config import Settings
from tracelink.serverless_dispatcher import dispatch_serverless_safely

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


class ServerlessDispatchMiddleware(BaseHTTPMiddleware):
    """Advance one durable outbox event only while a serverless request is alive."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        dispatch_once: DispatchOnce = dispatch_serverless_safely,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.dispatch_once = dispatch_once

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self.settings.serverless_runtime and is_dispatch_trigger(
            request.method, request.url.path
        ):
            await self.dispatch_once(self.settings)
        return await call_next(request)


# Compatibility alias for downstream imports while the module is renamed in a later cleanup.
RequestTriggeredOutboxMiddleware = ServerlessDispatchMiddleware
