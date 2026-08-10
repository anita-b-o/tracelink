import pytest
from alembic import command
from sqlalchemy import text

from tests.integration.conftest import alembic_config
from tracelink.infrastructure.database import get_engine

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_migration_round_trip(migrated_database_url: str) -> None:
    _ = migrated_database_url
    command.downgrade(alembic_config(), "0003_research_connectors")
    async with get_engine().connect() as connection:
        mention_table = await connection.scalar(
            text("SELECT to_regclass('public.entity_mentions')")
        )
    assert mention_table is None
    command.upgrade(alembic_config(), "head")
    command.downgrade(alembic_config(), "0002_investigation_workflow")
    async with get_engine().connect() as connection:
        normalized_url_before_upgrade = await connection.scalar(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'sources' "
                "AND column_name = 'normalized_url'"
            )
        )
    assert normalized_url_before_upgrade is None
    command.upgrade(alembic_config(), "head")
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
        source_columns = set(
            await connection.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'sources'"
                )
            )
        )

    assert extension == "vector"
    assert {
        "investigations",
        "entities",
        "relationships",
        "embedding_records",
        "entity_mentions",
        "entity_resolution_candidates",
        "investigation_artifacts",
    } <= tables
    assert "normalized_url" in source_columns
