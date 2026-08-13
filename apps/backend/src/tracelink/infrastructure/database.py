from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection as PsycopgAsyncConnection
from sqlalchemy import MetaData, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from tracelink.core.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


metadata = Base.metadata


async def _register_vector_if_available(connection: PsycopgAsyncConnection[Any]) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        result = await cursor.fetchone()
    if result is not None and result[0]:
        await register_vector_async(connection)


def _register_vector(dbapi_connection: Any, _: Any) -> None:
    dbapi_connection.run_async(_register_vector_if_available)


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    connect_args = {
        "connect_timeout": settings.db_connect_timeout_seconds,
        "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
    }
    if settings.serverless_runtime:
        # The provider-side pooler owns connection reuse for ephemeral Functions.
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            poolclass=NullPool,
            connect_args=connect_args,
        )
    else:
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=settings.db_pool_recycle_seconds,
            connect_args=connect_args,
        )
    event.listen(engine.sync_engine, "connect", _register_vector)
    return engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_database_connection() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_database() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
        get_session_factory.cache_clear()
