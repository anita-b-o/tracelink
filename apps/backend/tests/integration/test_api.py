from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.infrastructure.database import get_session
from tracelink.main import app

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_minimal_investigation_and_entity_endpoints(db_session: AsyncSession) -> None:
    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            investigation_response = await client.post(
                "/api/investigations",
                json={"title": "  Ownership review  ", "original_query": "Who owns ACME?"},
            )
            assert investigation_response.status_code == 201
            investigation = investigation_response.json()
            assert investigation["title"] == "Ownership review"
            assert investigation["status"] == "DRAFT"

            listing_response = await client.get("/api/investigations")
            assert listing_response.status_code == 200
            assert [item["id"] for item in listing_response.json()] == [investigation["id"]]

            get_response = await client.get(f"/api/investigations/{investigation['id']}")
            assert get_response.status_code == 200

            entity_response = await client.post(
                "/api/entities",
                json={
                    "type": "COMPANY",
                    "canonical_name": "ＡＣＭＥ Holdings",
                    "aliases": ["ACME"],
                    "metadata": {"country": "AR"},
                },
            )
            assert entity_response.status_code == 201
            entity = entity_response.json()
            assert entity["normalized_name"] == "acme holdings"
            assert entity["aliases"][0]["normalized_alias"] == "acme"

            entity_get = await client.get(f"/api/entities/{entity['id']}")
            assert entity_get.status_code == 200
            assert entity_get.json()["metadata"] == {"country": "AR"}

            assert (
                await client.get(f"/api/entities/{'0' * 8}-0000-0000-0000-000000000000")
            ).status_code == 404
            invalid = await client.post(
                "/api/entities", json={"type": "INVALID", "canonical_name": "X"}
            )
            assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()
