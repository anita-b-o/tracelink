from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def build_cache_key(connector: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"tracelink:research:v1:cache:{connector}:{digest}"


class ConnectorCache:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def get(self, key: str) -> str | None:
        try:
            value = await self.redis.get(key)
        except RedisError:
            logger.warning("research cache read failed")
            return None
        return str(value) if value is not None else None

    async def set(self, key: str, value: str) -> None:
        try:
            await self.redis.set(key, value, ex=self.ttl_seconds)
        except RedisError:
            logger.warning("research cache write failed")
