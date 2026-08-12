import asyncio
import logging
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tracelink.infrastructure.database import check_database_connection
from tracelink.infrastructure.redis import check_redis_connection

router = APIRouter()
logger = logging.getLogger(__name__)


class ComponentStatus(StrEnum):
    UP = "up"
    DOWN = "down"


class ComponentHealth(BaseModel):
    status: ComponentStatus
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["tracelink-api"] = "tracelink-api"


class ReadinessChecks(BaseModel):
    database: ComponentHealth
    redis: ComponentHealth


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


async def database_health() -> ComponentHealth:
    try:
        await asyncio.wait_for(check_database_connection(), timeout=3)
    except Exception:
        logger.warning("Database readiness check failed")
        return ComponentHealth(status=ComponentStatus.DOWN, detail="connection failed")
    return ComponentHealth(status=ComponentStatus.UP)


async def redis_health() -> ComponentHealth:
    try:
        await asyncio.wait_for(check_redis_connection(), timeout=3)
    except Exception:
        logger.warning("Redis readiness check failed")
        return ComponentHealth(status=ComponentStatus.DOWN, detail="connection failed")
    return ComponentHealth(status=ComponentStatus.UP)


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(
    database: Annotated[ComponentHealth, Depends(database_health)],
    redis: Annotated[ComponentHealth, Depends(redis_health)],
) -> ReadinessResponse | JSONResponse:
    checks = ReadinessChecks(database=database, redis=redis)
    is_ready = all(component.status is ComponentStatus.UP for component in (database, redis))
    response = ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
    if not is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(mode="json"),
        )
    return response
