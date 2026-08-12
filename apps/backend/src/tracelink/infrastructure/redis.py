import asyncio
from typing import cast
from weakref import WeakKeyDictionary

from redis.asyncio import Redis

from tracelink.core.config import get_settings

_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, Redis] = WeakKeyDictionary()


def _new_client() -> Redis:
    settings = get_settings()
    return cast(
        Redis,
        Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            health_check_interval=settings.redis_health_check_interval_seconds,
            retry_on_timeout=True,
        ),
    )


def get_redis_client() -> Redis:
    """Return one connection pool per event loop (workers and pytest use multiple loops)."""
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None:
        client = _new_client()
        _clients[loop] = client
    return client


def clear_redis_clients() -> None:
    _clients.clear()


async def check_redis_connection() -> None:
    await get_redis_client().ping()


async def close_redis() -> None:
    loop = asyncio.get_running_loop()
    client = _clients.pop(loop, None)
    if client is not None:
        await client.aclose()
