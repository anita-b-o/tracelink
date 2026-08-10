from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tracelink.api.routes.health import (
    ComponentHealth,
    ComponentStatus,
    database_health,
    redis_health,
)
from tracelink.main import app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def health_override(status: ComponentStatus) -> Callable[[], Awaitable[ComponentHealth]]:
    async def override() -> ComponentHealth:
        detail = None if status is ComponentStatus.UP else "unavailable in test"
        return ComponentHealth(status=status, detail=detail)

    return override


@pytest.mark.asyncio
async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tracelink-api"}


@pytest.mark.asyncio
async def test_readiness_when_dependencies_are_available(client: AsyncClient) -> None:
    app.dependency_overrides[database_health] = health_override(ComponentStatus.UP)
    app.dependency_overrides[redis_health] = health_override(ComponentStatus.UP)

    response = await client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": {"status": "up", "detail": None},
            "redis": {"status": "up", "detail": None},
        },
    }


@pytest.mark.parametrize("failed_dependency", ["database", "redis"])
@pytest.mark.asyncio
async def test_readiness_exposes_degraded_component(
    client: AsyncClient, failed_dependency: str
) -> None:
    database_status = (
        ComponentStatus.DOWN if failed_dependency == "database" else ComponentStatus.UP
    )
    redis_status = ComponentStatus.DOWN if failed_dependency == "redis" else ComponentStatus.UP
    app.dependency_overrides[database_health] = health_override(database_status)
    app.dependency_overrides[redis_health] = health_override(redis_status)

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"][failed_dependency]["status"] == "down"
