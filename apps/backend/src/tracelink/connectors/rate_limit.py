from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from tracelink.connectors.errors import ConnectorRateLimitError

Sleep = Callable[[float], Awaitable[None]]

RATE_LIMIT_SCRIPT = """
local now = redis.call('TIME')
local second = now[1]
local bucket = KEYS[1] .. ':' .. second
local count = redis.call('INCR', bucket)
if count == 1 then redis.call('PEXPIRE', bucket, 2000) end
if count <= tonumber(ARGV[1]) then return 0 end
return 1000 - math.floor(tonumber(now[2]) / 1000)
"""


def build_rate_limit_key(connector: str, source: str) -> str:
    digest = hashlib.sha256(source.casefold().encode()).hexdigest()[:24]
    return f"tracelink:research:v1:rate:{connector}:{digest}"


class ConnectorRateLimiter:
    def __init__(self, redis: Redis, *, sleep: Sleep = asyncio.sleep) -> None:
        self.redis = redis
        self.sleep = sleep

    async def acquire(self, connector: str, source: str, requests_per_second: int) -> None:
        key = build_rate_limit_key(connector, source)
        while True:
            try:
                pending = cast(
                    Awaitable[Any],
                    self.redis.eval(RATE_LIMIT_SCRIPT, 1, key, str(requests_per_second)),
                )
                wait_ms = int(await pending)
            except RedisError as exc:
                raise ConnectorRateLimitError("research rate limiter is unavailable") from exc
            if wait_ms <= 0:
                return
            await self.sleep(wait_ms / 1000)
