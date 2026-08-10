from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from tracelink.connectors.errors import (
    ConnectorFetchError,
    ConnectorTimeoutError,
    ResponseTooLargeError,
    UnsafeUrlError,
    UnsupportedContentTypeError,
)
from tracelink.connectors.http import ResearchHttpClient
from tracelink.connectors.models import ConnectorFetchResult
from tracelink.connectors.url_safety import UrlSafetyValidator
from tracelink.core.config import Settings


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value


class CountingRateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self, connector: str, source: str, requests_per_second: int) -> None:
        _ = (connector, source, requests_per_second)
        self.calls += 1


async def public_resolver(host: str, port: int) -> tuple[str, ...]:
    _ = port
    if host.startswith("127."):
        return (host,)
    return ("93.184.216.34",)


def make_client(
    handler: Any,
    *,
    max_bytes: int = 5000,
) -> tuple[ResearchHttpClient, MemoryCache, CountingRateLimiter, list[float]]:
    cache = MemoryCache()
    limiter = CountingRateLimiter()
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = ResearchHttpClient(
        Settings(research_http_max_response_bytes=max_bytes),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        validator=UrlSafetyValidator(resolver=public_resolver),
        cache=cache,  # type: ignore[arg-type]
        rate_limiter=limiter,  # type: ignore[arg-type]
        sleep=sleep,
    )
    return client, cache, limiter, sleeps


@pytest.mark.asyncio
async def test_fetch_cache_hit_avoids_second_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"content-type": "text/html"}, text="ok")

    client, _, limiter, _ = make_client(handler)
    first = await client.fetch(
        "https://public.example/", connector="html", allowed_content_types=frozenset({"text/html"})
    )
    second = await client.fetch(
        "https://public.example/", connector="html", allowed_content_types=frozenset({"text/html"})
    )
    await client.close()
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert calls == limiter.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 503])
async def test_transient_statuses_are_retried(status_code: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(
                status_code,
                headers={"retry-after": "0", "content-type": "text/html"},
            )
        return httpx.Response(200, headers={"content-type": "text/html"}, text="ok")

    client, _, limiter, sleeps = make_client(handler)
    result = await client.fetch(
        "https://public.example/", connector="html", allowed_content_types=frozenset({"text/html"})
    )
    await client.close()
    assert result.retry_count == 2
    assert calls == limiter.calls == 3
    assert sleeps == [0.0, 0.0]


@pytest.mark.asyncio
async def test_404_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, headers={"content-type": "text/html"})

    client, _, _, _ = make_client(handler)
    with pytest.raises(ConnectorFetchError) as error:
        await client.fetch(
            "https://public.example/",
            connector="html",
            allowed_content_types=frozenset({"text/html"}),
        )
    await client.close()
    assert error.value.status_code == 404
    assert calls == 1


@pytest.mark.asyncio
async def test_redirect_target_is_revalidated_and_private_target_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client, _, _, _ = make_client(handler)
    with pytest.raises(UnsafeUrlError):
        await client.fetch(
            "https://public.example/",
            connector="html",
            allowed_content_types=frozenset({"text/html"}),
        )
    await client.close()


@pytest.mark.asyncio
async def test_response_size_and_content_type_are_enforced() -> None:
    def too_large(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"123456")

    client, _, _, _ = make_client(too_large, max_bytes=5)
    with pytest.raises(ResponseTooLargeError):
        await client.fetch(
            "https://public.example/",
            connector="html",
            allowed_content_types=frozenset({"text/html"}),
        )
    await client.close()

    def json_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, text="{}")

    client, _, _, _ = make_client(json_response)
    with pytest.raises(UnsupportedContentTypeError):
        await client.fetch(
            "https://public.example/",
            connector="html",
            allowed_content_types=frozenset({"text/html"}),
        )
    await client.close()


@pytest.mark.asyncio
async def test_read_timeout_retries_then_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client, _, limiter, sleeps = make_client(handler)
    with pytest.raises(ConnectorTimeoutError):
        await client.fetch(
            "https://public.example/",
            connector="html",
            allowed_content_types=frozenset({"text/html"}),
        )
    await client.close()
    assert limiter.calls == 3
    assert sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_cached_fetch_model_is_serializable() -> None:
    result = ConnectorFetchResult(
        url="https://example.com/",
        status_code=200,
        content_type="text/html",
        text="ok",
        retrieved_at=datetime.now(UTC),
    )
    assert ConnectorFetchResult.model_validate_json(result.model_dump_json()) == result
