from __future__ import annotations

import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tracelink.core.config import get_settings
from tracelink.domain.enums import OutboxStatus, ResearchTaskStatus
from tracelink.domain.models import Investigation, OutboxEvent, ResearchTask
from tracelink.infrastructure.database import get_session
from tracelink.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
INVESTIGATION_STATUS = Gauge("tracelink_investigations", "Investigations by status", ("status",))
OUTBOX_EVENTS = Gauge("tracelink_outbox_events", "Outbox events by status", ("status",))
STUCK_TASKS = Gauge("tracelink_stuck_research_tasks", "Stale running research tasks")


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def metrics_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, metrics_send)
        finally:
            route = scope.get("route")
            route_label = getattr(route, "path", "unmatched")
            method = str(scope.get("method", "UNKNOWN"))
            HTTP_REQUESTS.labels(method, route_label, f"{status_code // 100}xx").inc()
            HTTP_LATENCY.labels(method, route_label).observe(time.perf_counter() - started)


@router.get("/metrics", include_in_schema=False)
async def metrics(
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    configured = get_settings().metrics_bearer_token
    expected = configured.get_secret_value() if configured else ""
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")

    for name, count in (
        await session.execute(
            select(Investigation.status, func.count(Investigation.id)).group_by(
                Investigation.status
            )
        )
    ).all():
        INVESTIGATION_STATUS.labels(name.value).set(int(count))
    for name, count in (
        await session.execute(
            select(OutboxEvent.status, func.count(OutboxEvent.id)).group_by(OutboxEvent.status)
        )
    ).all():
        OUTBOX_EVENTS.labels(name.value).set(int(count))
    stuck = await session.scalar(
        select(func.count(ResearchTask.id)).where(
            ResearchTask.status == ResearchTaskStatus.RUNNING,
            ResearchTask.started_at < func.now() - text("interval '1 hour'"),
        )
    )
    STUCK_TASKS.set(int(stuck or 0))
    for status_name in OutboxStatus:
        OUTBOX_EVENTS.labels(status_name.value)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
