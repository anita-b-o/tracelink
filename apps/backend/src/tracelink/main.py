from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tracelink.api.router import api_router
from tracelink.connectors.http import close_research_http_client
from tracelink.core.config import get_settings
from tracelink.core.logging import configure_logging
from tracelink.infrastructure.database import close_database
from tracelink.infrastructure.redis import close_redis

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_research_http_client()
    await close_database()
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description="Evidence-first OSINT research API with entity extraction and resolution.",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(api_router, prefix="/api")
