from __future__ import annotations

import hashlib
from typing import Any, Protocol

import httpx
from pydantic import SecretStr, ValidationError

from tracelink.connectors.errors import (
    WebSearchAuthenticationError,
    WebSearchConfigurationError,
    WebSearchInvalidResponseError,
    WebSearchRateLimitError,
    WebSearchTimeoutError,
    WebSearchUpstreamError,
)
from tracelink.connectors.models import ConnectorSearchResult

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class WebSearchProvider(Protocol):
    name: str
    enabled: bool

    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]: ...


class DisabledWebSearchProvider:
    name = "disabled"
    enabled = False

    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]:
        _ = (query, limit)
        raise WebSearchConfigurationError()


class FakeWebSearchProvider:
    name = "fake"
    enabled = True

    def __init__(self, results: list[ConnectorSearchResult] | None = None) -> None:
        self.results = results

    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]:
        if self.results is not None:
            return self.results[:limit]
        digest = hashlib.sha256(query.encode()).hexdigest()[:12]
        return [
            ConnectorSearchResult(
                external_id=f"fake-{digest}-{rank}",
                url=f"https://example.com/research/{digest}/{rank}",
                title=f"Public result {rank}",
                snippet="Deterministic public search fixture",
                rank=rank,
                metadata={"provider": self.name},
            )
            for rank in range(1, min(limit, 3) + 1)
        ]


class BraveWebSearchProvider:
    """Small adapter for Brave Search's server-side Web Search API."""

    name = "brave"
    enabled = True

    def __init__(
        self,
        api_key: SecretStr,
        timeout_seconds: float,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = client

    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]:
        if self._client is None:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await self._request(client, query, limit)
        else:
            response = await self._request(self._client, query, limit)
        return self._parse(response)

    async def _request(self, client: httpx.AsyncClient, query: str, limit: int) -> httpx.Response:
        try:
            response = await client.get(
                BRAVE_SEARCH_URL,
                params={"q": query, "count": min(limit, 20)},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key.get_secret_value(),
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise WebSearchTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise WebSearchUpstreamError() from exc
        if response.status_code in {401, 403}:
            raise WebSearchAuthenticationError(status_code=response.status_code)
        if response.status_code == 429:
            raise WebSearchRateLimitError(status_code=429)
        if response.status_code >= 500:
            raise WebSearchUpstreamError(status_code=response.status_code)
        if response.status_code >= 400:
            raise WebSearchUpstreamError(status_code=response.status_code)
        return response

    @staticmethod
    def _parse(response: httpx.Response) -> list[ConnectorSearchResult]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise WebSearchInvalidResponseError() from exc
        if not isinstance(payload, dict):
            raise WebSearchInvalidResponseError()
        web = payload.get("web")
        if web is None:
            return []
        if not isinstance(web, dict):
            raise WebSearchInvalidResponseError()
        raw_results = web.get("results", [])
        if not isinstance(raw_results, list):
            raise WebSearchInvalidResponseError()

        results: list[ConnectorSearchResult] = []
        for position, raw in enumerate(raw_results, start=1):
            if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
                raise WebSearchInvalidResponseError()
            metadata: dict[str, Any] = {"provider": "brave"}
            for key in ("type", "subtype", "language", "family_friendly"):
                value = raw.get(key)
                if isinstance(value, (str, bool, int, float)):
                    metadata[key] = value
            try:
                results.append(
                    ConnectorSearchResult(
                        external_id=(
                            str(raw["id"]) if isinstance(raw.get("id"), (str, int)) else None
                        ),
                        url=raw["url"],
                        title=raw.get("title") if isinstance(raw.get("title"), str) else None,
                        snippet=(
                            raw.get("description")
                            if isinstance(raw.get("description"), str)
                            else None
                        ),
                        rank=position,
                        metadata=metadata,
                    )
                )
            except ValidationError as exc:
                raise WebSearchInvalidResponseError() from exc
        return results
