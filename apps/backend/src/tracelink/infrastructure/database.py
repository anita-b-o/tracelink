from functools import lru_cache

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tracelink.core.config import get_settings

metadata = MetaData()


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def check_database_connection() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_database() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
