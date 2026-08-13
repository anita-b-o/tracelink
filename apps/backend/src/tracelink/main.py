import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.types import Event
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tracelink.api.metrics import MetricsMiddleware
from tracelink.api.metrics import router as metrics_router
from tracelink.api.router import api_router
from tracelink.api.security import RequestSecurityMiddleware
from tracelink.connectors.http import close_research_http_client
from tracelink.core.config import get_settings
from tracelink.core.logging import configure_logging
from tracelink.infrastructure.database import close_database
from tracelink.infrastructure.redis import close_redis

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def scrub_sentry_event(event: Event, _: dict[str, Any]) -> Event:
    event.pop("user", None)
    request_data = event.get("request")
    if isinstance(request_data, dict):
        request_data.pop("data", None)
        request_data.pop("cookies", None)
        request_data.pop("query_string", None)
        headers = request_data.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if str(key).lower() in {"authorization", "cookie", "x-csrf-token"}:
                    headers.pop(key, None)
    return event


if settings.sentry_dsn is not None and settings.sentry_dsn.get_secret_value().strip():
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        before_send=scrub_sentry_event,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    demo_stop: asyncio.Event | None = None
    demo_task: asyncio.Task[None] | None = None
    if settings.demo_mode:
        from tracelink.demo_dispatcher import run_demo_dispatcher

        demo_stop = asyncio.Event()
        demo_task = asyncio.create_task(run_demo_dispatcher(demo_stop), name="demo-outbox")
    try:
        yield
    finally:
        if demo_stop is not None and demo_task is not None:
            demo_stop.set()
            demo_task.cancel()
            with suppress(asyncio.CancelledError):
                await demo_task
        await close_research_http_client()
        await close_database()
        await close_redis()


app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description="Evidence-first OSINT research API with entity extraction and resolution.",
    docs_url="/docs" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
app.add_middleware(RequestSecurityMiddleware, settings=settings)
app.include_router(api_router, prefix="/api")
app.include_router(metrics_router)
app.add_middleware(MetricsMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    error_id = str(uuid.uuid4())
    request_id = request.state.request_id
    logger.exception(
        "unhandled request error",
        extra={"status_code": 500, "request_id": request_id, "error_id": error_id},
    )
    sentry_sdk.capture_exception(exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error", "error_id": error_id, "request_id": request_id},
    )
