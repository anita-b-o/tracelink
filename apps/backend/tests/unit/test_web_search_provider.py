from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from tracelink.connectors.errors import (
    ConnectorError,
    WebSearchAuthenticationError,
    WebSearchInvalidResponseError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
    WebSearchUpstreamError,
)
from tracelink.connectors.providers import BRAVE_SEARCH_URL, BraveWebSearchProvider


def provider(handler: Any, api_key: str = "super-secret-search-key") -> BraveWebSearchProvider:
    return BraveWebSearchProvider(
        SecretStr(api_key),
        2,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_brave_provider_normalizes_valid_response_without_exposing_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(BRAVE_SEARCH_URL)
        assert request.headers["X-Subscription-Token"] == "super-secret-search-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://example.com/profile",
                            "title": "Jane Recruiter",
                            "description": "Jane works at Acme Corp.",
                            "language": "en",
                        }
                    ]
                }
            },
        )

    search = provider(handler)
    results = await search.search("Acme recruiters", 10)

    assert len(results) == 1
    assert results[0].url == "https://example.com/profile"
    assert results[0].rank == 1
    assert results[0].metadata == {"provider": "brave", "language": "en"}
    assert "super-secret-search-key" not in repr(search)


@pytest.mark.asyncio
async def test_brave_provider_accepts_zero_results() -> None:
    search = provider(lambda request: httpx.Response(200, json={"web": {"results": []}}))
    assert await search.search("no matches", 10) == []


@pytest.mark.asyncio
async def test_brave_provider_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret should not be copied", request=request)

    with pytest.raises(WebSearchTimeoutError) as error:
        await provider(handler).search("query", 10)
    assert "super-secret-search-key" not in repr(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, WebSearchAuthenticationError),
        (403, WebSearchAuthenticationError),
        (429, WebSearchRateLimitError),
        (500, WebSearchUpstreamError),
        (503, WebSearchUpstreamError),
    ],
)
async def test_brave_provider_maps_http_failures(
    status_code: int, error_type: type[ConnectorError]
) -> None:
    search = provider(lambda request: httpx.Response(status_code, text="do not persist body"))
    with pytest.raises(error_type) as error:
        await search.search("query", 10)
    assert error.value.status_code == status_code
    assert "do not persist body" not in repr(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"web": {"results": "invalid"}}),
    ],
)
async def test_brave_provider_rejects_invalid_json_shape(response: httpx.Response) -> None:
    search = provider(lambda request: response)
    with pytest.raises(WebSearchInvalidResponseError):
        await search.search("query", 10)
