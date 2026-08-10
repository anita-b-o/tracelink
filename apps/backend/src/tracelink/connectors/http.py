from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from tracelink.connectors.cache import ConnectorCache, build_cache_key
from tracelink.connectors.errors import (
    ConnectorFetchError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ResponseTooLargeError,
    UnsupportedContentTypeError,
)
from tracelink.connectors.models import ConnectorFetchResult
from tracelink.connectors.rate_limit import ConnectorRateLimiter
from tracelink.connectors.url_safety import UrlSafetyValidator
from tracelink.core.config import Settings, get_settings
from tracelink.infrastructure.redis import get_redis_client

logger = logging.getLogger(__name__)

TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 8.0
Sleep = Callable[[float], Awaitable[None]]


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        delay = (target - datetime.now(UTC)).total_seconds()
    return max(0.0, min(delay, MAX_RETRY_DELAY_SECONDS))


class ResearchHttpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        validator: UrlSafetyValidator | None = None,
        cache: ConnectorCache | None = None,
        rate_limiter: ConnectorRateLimiter | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(settings.research_http_timeout_seconds),
            trust_env=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": settings.research_http_user_agent},
        )
        redis = get_redis_client()
        self.validator = validator or UrlSafetyValidator()
        self.cache = cache or ConnectorCache(redis, settings.research_cache_ttl_seconds)
        self.rate_limiter = rate_limiter or ConnectorRateLimiter(redis)
        self.sleep = sleep

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def fetch(
        self,
        url: str,
        *,
        connector: str,
        allowed_content_types: frozenset[str],
        requests_per_second: int | None = None,
    ) -> ConnectorFetchResult:
        started = time.monotonic()
        validated = await self.validator.validate(url)
        rate = requests_per_second or self.settings.research_connector_requests_per_second
        key = build_cache_key(
            connector,
            {
                "url": validated.normalized_url,
                "content_types": sorted(allowed_content_types),
                "max_bytes": self.settings.research_http_max_response_bytes,
            },
        )
        cached = await self.cache.get(key)
        if cached is not None:
            try:
                result = ConnectorFetchResult.model_validate_json(cached)
            except ValueError:
                logger.warning("research cache value was invalid", extra={"connector": connector})
            else:
                result.cache_hit = True
                self._log_fetch(result, connector, started)
                return result

        current_url = validated.normalized_url
        visited: set[str] = set()
        total_retries = 0
        for _ in range(self.settings.research_http_max_redirects + 1):
            current = await self.validator.validate(current_url)
            if current.normalized_url in visited:
                raise ConnectorFetchError("the public source returned a redirect loop")
            visited.add(current.normalized_url)
            response, body, retries = await self._request_with_retries(
                current.normalized_url,
                connector=connector,
                host=current.host,
                requests_per_second=rate,
            )
            total_retries += retries
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise ConnectorFetchError(
                        "the public source returned an invalid redirect",
                        status_code=response.status_code,
                    )
                current_url = urljoin(current.normalized_url, location)
                continue
            if response.status_code >= 400:
                raise ConnectorFetchError(status_code=response.status_code)

            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in allowed_content_types:
                raise UnsupportedContentTypeError(status_code=response.status_code)
            encoding = response.encoding or "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            result = ConnectorFetchResult(
                url=current.normalized_url,
                status_code=response.status_code,
                content_type=content_type,
                text=text,
                retrieved_at=datetime.now(UTC),
                metadata={
                    "final_url": current.normalized_url,
                    "content_length": len(body),
                    **self._safe_headers(response),
                },
                retry_count=total_retries,
            )
            await self.cache.set(key, result.model_dump_json())
            self._log_fetch(result, connector, started)
            return result
        raise ConnectorFetchError("the public source exceeded the redirect limit")

    async def _request_with_retries(
        self,
        url: str,
        *,
        connector: str,
        host: str,
        requests_per_second: int,
    ) -> tuple[httpx.Response, bytes, int]:
        for attempt in range(MAX_ATTEMPTS):
            await self.rate_limiter.acquire(connector, host, requests_per_second)
            try:
                response, body = await self._request(url)
            except (httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise ConnectorTimeoutError() from exc
                await self.sleep(min(0.5 * (2**attempt), MAX_RETRY_DELAY_SECONDS))
                continue
            except httpx.HTTPError as exc:
                raise ConnectorFetchError() from exc
            if response.status_code not in TRANSIENT_STATUSES:
                return response, body, attempt
            if attempt + 1 == MAX_ATTEMPTS:
                if response.status_code == 429:
                    raise ConnectorRateLimitError(status_code=429)
                raise ConnectorFetchError(status_code=response.status_code)
            delay = _retry_after_seconds(response.headers.get("retry-after"))
            if delay is None:
                delay = min(0.5 * (2**attempt), MAX_RETRY_DELAY_SECONDS)
            await self.sleep(delay)
        raise AssertionError("unreachable")

    async def _request(self, url: str) -> tuple[httpx.Response, bytes]:
        async with self.client.stream("GET", url) as response:
            declared = response.headers.get("content-length")
            if declared is not None:
                try:
                    if int(declared) > self.settings.research_http_max_response_bytes:
                        raise ResponseTooLargeError(status_code=response.status_code)
                except ValueError:
                    pass
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.settings.research_http_max_response_bytes:
                    raise ResponseTooLargeError(status_code=response.status_code)
                chunks.append(chunk)
            return response, b"".join(chunks)

    @staticmethod
    def _safe_headers(response: httpx.Response) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if value := response.headers.get("etag"):
            result["etag"] = value
        if value := response.headers.get("last-modified"):
            result["last_modified"] = value
        return result

    @staticmethod
    def _log_fetch(result: ConnectorFetchResult, connector: str, started: float) -> None:
        logger.info(
            "research connector fetch completed",
            extra={
                "connector": connector,
                "url_host": urlsplit(result.url).hostname,
                "status_code": result.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "cache_hit": result.cache_hit,
                "retry_count": result.retry_count,
            },
        )


@lru_cache
def get_research_http_client() -> ResearchHttpClient:
    return ResearchHttpClient(get_settings())


async def close_research_http_client() -> None:
    if get_research_http_client.cache_info().currsize:
        await get_research_http_client().close()
        get_research_http_client.cache_clear()
