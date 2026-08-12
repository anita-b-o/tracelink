from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from tracelink.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)

RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
local ttl = redis.call('TTL', KEYS[1])
if count > tonumber(ARGV[1]) then return ttl end
return -1
"""


@dataclass(frozen=True, slots=True)
class RatePolicy:
    name: str
    limit: int
    window_seconds: int


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(request: Request, policy: RatePolicy, identity: str) -> None:
    digest = hashlib.sha256(identity.casefold().encode()).hexdigest()[:32]
    key = f"tracelink:api-rate:v1:{policy.name}:{digest}"
    try:
        operation = cast(
            Awaitable[Any],
            get_redis_client().eval(
                RATE_LIMIT_SCRIPT,
                1,
                key,
                str(policy.limit),
                str(policy.window_seconds),
            ),
        )
        retry_after = int(await operation)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rate limiter unavailable",
        ) from exc
    if retry_after >= 0:
        logger.warning(
            "API rate limit exceeded",
            extra={"rate_limit_policy": policy.name, "status_code": 429},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests",
            headers={"Retry-After": str(max(retry_after, 1))},
        )
