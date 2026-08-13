from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from tracelink.api.security import RequestSecurityMiddleware
from tracelink.core.config import Settings
from tracelink.services.auth import AuthenticationError, AuthService


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "cors_allowed_origins": "https://app.example.com",
        "allowed_hosts": "api.internal,127.0.0.1",
        "auth_jwt_secret": "a" * 40,
        "auth_token_pepper": "b" * 40,
        "cookie_secure": True,
        "registration_enabled": False,
        "embedding_provider": "openai",
        "llm_provider": "openai",
        "openai_api_key": "placeholder-for-validation",
        "e2e_seed_enabled": False,
        "test_auth_bypass": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _demo_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "demo",
        "demo_mode": True,
        "cors_allowed_origins": "https://tracelink-demo-web.onrender.com",
        "allowed_hosts": "tracelink-demo-api.onrender.com",
        "auth_jwt_secret": "a" * 40,
        "auth_token_pepper": "b" * 40,
        "cookie_secure": True,
        "registration_enabled": True,
        "embedding_provider": "openai",
        "llm_provider": "openai",
        "openai_api_key": "placeholder-for-validation",
        "test_auth_bypass": False,
        "outbox_batch_size": 1,
        "outbox_lease_seconds": 360,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_production_configuration_rejects_fake_and_e2e_modes() -> None:
    with pytest.raises(ValidationError, match="fake AI providers are forbidden"):
        _production_settings(embedding_provider="fake")
    with pytest.raises(ValidationError, match="E2E/fake research modes are forbidden"):
        _production_settings(e2e_seed_enabled=True)


def test_demo_configuration_is_explicit_and_isolated() -> None:
    settings = _demo_settings()

    assert settings.app_env == "demo"
    assert settings.demo_mode is True
    assert settings.test_auth_bypass is False
    assert settings.secure_cookies is True
    assert settings.registration_is_enabled is True
    assert settings.allowed_host_list == [
        "tracelink-demo-api.onrender.com",
        "127.0.0.1",
    ]

    for app_env in ("development", "test", "staging", "production"):
        with pytest.raises(ValidationError, match="required only when APP_ENV=demo"):
            _production_settings(app_env=app_env, demo_mode=True)
    with pytest.raises(ValidationError, match="required only when APP_ENV=demo"):
        _demo_settings(demo_mode=False)
    with pytest.raises(ValidationError, match="only allowed in test"):
        _demo_settings(test_auth_bypass=True)


def test_demo_configuration_keeps_deployment_security_invariants() -> None:
    with pytest.raises(ValidationError, match="fake AI providers are forbidden"):
        _demo_settings(embedding_provider="fake")
    with pytest.raises(ValidationError, match="E2E/fake research modes are forbidden"):
        _demo_settings(fake_research_mode="SUCCESS")
    with pytest.raises(ValidationError, match="secure cookies"):
        _demo_settings(cookie_secure=False)
    with pytest.raises(ValidationError, match="OUTBOX_BATCH_SIZE=1"):
        _demo_settings(outbox_batch_size=2)
    with pytest.raises(ValidationError, match="lease must exceed"):
        _demo_settings(outbox_lease_seconds=330)


def test_production_configuration_rejects_weak_secrets_and_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="distinct and at least 32 bytes"):
        _production_settings(auth_jwt_secret="short")
    with pytest.raises(ValidationError, match="wildcard CORS"):
        _production_settings(cors_allowed_origins="*")
    with pytest.raises(ValidationError, match="explicit hostnames"):
        _production_settings(allowed_hosts="*")


def test_production_configuration_adds_loopback_for_container_healthchecks() -> None:
    settings = _production_settings(allowed_hosts="api.internal")

    assert settings.allowed_host_list == ["api.internal", "127.0.0.1"]


def test_expired_access_token_is_rejected() -> None:
    settings = Settings(app_env="test", test_auth_bypass=False)
    service = AuthService(None, settings)  # type: ignore[arg-type]
    token = service._encode(
        user_id=uuid4(),
        session_id=uuid4(),
        token_type="access",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(AuthenticationError, match="invalid session"):
        service.decode(token, "access")


@pytest.mark.asyncio
async def test_security_middleware_enforces_csrf_size_headers_and_request_id() -> None:
    inner = FastAPI()

    @inner.api_route("/api/echo", methods=["GET", "POST"])
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    settings = Settings(
        app_env="development",
        cors_allowed_origins="http://allowed.test",
        max_request_body_bytes=1024,
        test_auth_bypass=False,
    )
    secured = RequestSecurityMiddleware(inner, settings)
    async with AsyncClient(
        transport=ASGITransport(app=secured), base_url="http://allowed.test"
    ) as client:
        missing = await client.post("/api/echo", content=b"ok")
        assert missing.status_code == 403

        client.cookies.set("tracelink_csrf", "csrf-value")
        accepted = await client.post(
            "/api/echo",
            content=b"ok",
            headers={
                "Origin": "http://allowed.test",
                "X-CSRF-Token": "csrf-value",
                "X-Request-ID": "phase8-test",
            },
        )
        assert accepted.status_code == 200
        assert accepted.headers["x-request-id"] == "phase8-test"
        assert accepted.headers["x-content-type-options"] == "nosniff"
        assert accepted.headers["referrer-policy"] == "strict-origin-when-cross-origin"

        async def oversized() -> AsyncIterator[bytes]:
            yield b"x" * 700
            yield b"y" * 700

        too_large = await client.post(
            "/api/echo",
            content=oversized(),
            headers={"Origin": "http://allowed.test", "X-CSRF-Token": "csrf-value"},
        )
        assert too_large.status_code == 413
