import pytest
from alembic import command
from sqlalchemy import text

from tests.integration.conftest import alembic_config
from tracelink.infrastructure.database import get_engine

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_migration_round_trip(migrated_database_url: str) -> None:
    _ = migrated_database_url
    command.downgrade(alembic_config(), "0001_core_domain")
    command.upgrade(alembic_config(), "head")
    command.downgrade(alembic_config(), "0001_core_domain")
    command.upgrade(alembic_config(), "head")

    async with get_engine().connect() as connection:
        extension = await connection.scalar(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        tables = set(
            await connection.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        )

    assert extension == "vector"
    assert {"investigations", "entities", "relationships", "embedding_records"} <= tables
