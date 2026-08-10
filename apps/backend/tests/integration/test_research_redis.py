from __future__ import annotations

from uuid import uuid4

import pytest

from tracelink.connectors.cache import ConnectorCache
from tracelink.connectors.rate_limit import ConnectorRateLimiter, build_rate_limit_key
from tracelink.infrastructure.redis import get_redis_client

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_real_redis_cache_and_rate_limit_backend() -> None:
    redis = get_redis_client()
    suffix = uuid4().hex
    cache_key = f"tracelink:research:test:cache:{suffix}"
    source = f"source-{suffix}"
    rate_key = build_rate_limit_key("integration", source)
    try:
        cache = ConnectorCache(redis, 30)
        await cache.set(cache_key, '{"ok":true}')
        assert await cache.get(cache_key) == '{"ok":true}'
        ttl = await redis.ttl(cache_key)
        assert 0 < ttl <= 30

        limiter = ConnectorRateLimiter(redis)
        await limiter.acquire("integration", source, 2)
        await limiter.acquire("integration", source, 2)
        keys = [key async for key in redis.scan_iter(match=f"{rate_key}:*")]
        assert len(keys) == 1
        assert int(await redis.get(keys[0])) == 2
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{rate_key}:*")]
        if keys:
            await redis.delete(*keys)
        await redis.delete(cache_key)
