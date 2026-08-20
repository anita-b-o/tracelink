from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import NullPool

from tracelink.core.config import Settings
from tracelink.infrastructure import database
from tracelink.vercel_demo import RequestTriggeredOutboxMiddleware, is_dispatch_trigger


def test_dispatch_trigger_is_limited_to_demo_polling_routes() -> None:
    resource_id = uuid4()

    assert is_dispatch_trigger("GET", f"/api/investigations/{resource_id}")
    assert is_dispatch_trigger("GET", f"/api/investigations/{resource_id}/progress")
    assert is_dispatch_trigger("GET", f"/api/investigations/{resource_id}/reports")
    assert is_dispatch_trigger("GET", f"/api/reports/{resource_id}")
    assert not is_dispatch_trigger("GET", "/api/investigations")
    assert not is_dispatch_trigger("POST", f"/api/investigations/{resource_id}/start")
    assert not is_dispatch_trigger("GET", "/api/investigations/not-a-uuid")


@pytest.mark.asyncio
async def test_serverless_demo_advances_once_before_poll_response() -> None:
    inner = FastAPI()
    calls: list[Settings] = []

    @inner.get("/api/investigations/{investigation_id}")
    async def investigation(investigation_id: str) -> dict[str, str]:
        return {"id": investigation_id}

    async def dispatch_once(settings: Settings) -> int:
        calls.append(settings)
        return 1

    settings = Settings(app_env="test", serverless_runtime=True)
    settings.demo_mode = True
    app = RequestTriggeredOutboxMiddleware(
        inner,
        settings=settings,
        dispatch_once=dispatch_once,
    )
    resource_id = uuid4()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://demo.example"
    ) as client:
        response = await client.get(f"/api/investigations/{resource_id}")

    assert response.status_code == 200
    assert calls == [settings]


@pytest.mark.asyncio
async def test_non_demo_serverless_request_does_not_dispatch() -> None:
    inner = FastAPI()
    calls = 0

    @inner.get("/api/investigations/{investigation_id}")
    async def investigation(investigation_id: str) -> dict[str, str]:
        return {"id": investigation_id}

    async def dispatch_once(_: Settings) -> int:
        nonlocal calls
        calls += 1
        return 1

    app = RequestTriggeredOutboxMiddleware(
        inner,
        settings=Settings(app_env="test", serverless_runtime=True),
        dispatch_once=dispatch_once,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://demo.example"
    ) as client:
        response = await client.get(f"/api/investigations/{uuid4()}")

    assert response.status_code == 200
    assert calls == 0


def test_serverless_database_uses_provider_side_pooling(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        app_env="test",
        serverless_runtime=True,
        db_connect_timeout_seconds=7,
        db_statement_timeout_ms=4567,
    )
    connect_args: dict[str, Any] = {}
    create_async_engine = database.create_async_engine

    def capture_connect_args(url: str, **kwargs: Any) -> Any:
        connect_args.update(kwargs["connect_args"])
        return create_async_engine(url, **kwargs)

    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "create_async_engine", capture_connect_args)

    engine = database.get_engine()

    assert isinstance(engine.pool, NullPool)
    assert connect_args == {"connect_timeout": 7}
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()


def test_non_serverless_database_keeps_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        app_env="test",
        serverless_runtime=False,
        db_connect_timeout_seconds=7,
        db_statement_timeout_ms=4567,
    )
    connect_args: dict[str, Any] = {}
    create_async_engine = database.create_async_engine

    def capture_connect_args(url: str, **kwargs: Any) -> Any:
        connect_args.update(kwargs["connect_args"])
        return create_async_engine(url, **kwargs)

    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(database, "create_async_engine", capture_connect_args)

    database.get_engine()

    assert connect_args == {
        "connect_timeout": 7,
        "options": "-c statement_timeout=4567",
    }
    database.get_engine.cache_clear()
    database.get_session_factory.cache_clear()
