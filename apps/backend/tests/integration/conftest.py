import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tracelink.core.config import get_settings
from tracelink.infrastructure.database import close_database, get_session_factory

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    "investigation_reports",
    "embedding_records",
    "retrieval_chunks",
    "findings",
    "evidence",
    "relationship_candidates",
    "entity_resolution_candidates",
    "entity_mentions",
    "investigation_artifacts",
    "documents",
    "relationships",
    "entity_aliases",
    "research_tasks",
    "sources",
    "entities",
    "investigations",
)


def alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def migrated_database_url() -> AsyncIterator[str]:
    configured = os.getenv("TEST_DATABASE_URL")
    if configured is None:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    base_url = make_url(configured)
    database_name = f"tracelink_test_{uuid4().hex}"
    admin_url: URL = base_url.set(database="postgres")
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    test_url = base_url.set(database=database_name).render_as_string(hide_password=False)
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()

    try:
        command.upgrade(alembic_config(), "head")
        yield test_url
    finally:
        await close_database()
        get_settings.cache_clear()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(text(f'DROP DATABASE "{database_name}"'))
        await admin_engine.dispose()


@pytest_asyncio.fixture
async def db_session(migrated_database_url: str) -> AsyncIterator[AsyncSession]:
    _ = migrated_database_url
    async with get_session_factory()() as session:
        yield session
        await session.rollback()
    async with get_session_factory().begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
