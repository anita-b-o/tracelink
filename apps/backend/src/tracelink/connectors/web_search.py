from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from tracelink.connectors.cache import ConnectorCache, build_cache_key
from tracelink.connectors.errors import ConnectorError
from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorOutput,
    ConnectorSearchResult,
    SourceArtifact,
)
from tracelink.connectors.providers import WebSearchProvider
from tracelink.connectors.rate_limit import ConnectorRateLimiter
from tracelink.connectors.url_safety import UrlSafetyValidator, normalize_url
from tracelink.core.config import Settings
from tracelink.domain.enums import ResearchTaskType
from tracelink.domain.normalization import collapse_whitespace


class GenericWebSearchConnector:
    name = "web_search"
    supported_task_types = frozenset(
        {ResearchTaskType.WEB_SEARCH, ResearchTaskType.PUBLIC_MENTIONS}
    )
    requests_per_second: int | None = 1

    def __init__(
        self,
        provider: WebSearchProvider,
        settings: Settings,
        cache: ConnectorCache,
        rate_limiter: ConnectorRateLimiter,
        validator: UrlSafetyValidator | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.cache = cache
        self.rate_limiter = rate_limiter
        self.validator = validator or UrlSafetyValidator()

    def normalize(self, value: str) -> str:
        return collapse_whitespace(value)

    def _provider_query(self, query: str, task_type: ResearchTaskType | None) -> str:
        if task_type is ResearchTaskType.PUBLIC_MENTIONS:
            escaped = query.replace('"', '\\"')
            return f'"{escaped}"'
        return query

    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]:
        return await self.provider.search(query, limit)

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        query = self.normalize(value)
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        if not self.provider.enabled:
            return ConnectorOutput(
                connector=self.name,
                status="skipped",
                metadata={"reason": "web_search_provider_disabled", "query_hash": query_hash},
            )

        provider_query = self._provider_query(query, context.task_type)
        limit = self.settings.research_web_search_max_results
        key = build_cache_key(
            self.name,
            {"provider": self.provider.name, "query": provider_query, "limit": limit},
        )
        cache_hit = False
        cached = await self.cache.get(key)
        if cached is not None:
            try:
                results = [
                    ConnectorSearchResult.model_validate(item) for item in json.loads(cached)
                ]
            except (TypeError, ValueError):
                cached = None
            else:
                cache_hit = True
        if cached is None:
            await self.rate_limiter.acquire(
                self.name,
                self.provider.name,
                self.requests_per_second or self.settings.research_connector_requests_per_second,
            )
            results = await self.search(provider_query, limit)
            await self.cache.set(
                key,
                json.dumps(
                    [item.model_dump(mode="json") for item in results],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )

        artifacts: list[SourceArtifact] = []
        seen: set[str] = set()
        invalid_count = 0
        retrieved_at = datetime.now(UTC)
        for rank, item in enumerate(results[:limit], start=1):
            try:
                validated = await self.validator.validate(item.url)
            except ConnectorError:
                invalid_count += 1
                continue
            normalized = validated.normalized_url
            if normalized in seen:
                continue
            seen.add(normalized)
            artifacts.append(
                SourceArtifact(
                    source_type="web_page",
                    url=normalize_url(item.url),
                    normalized_url=normalized,
                    publisher=validated.host,
                    title=item.title[:500] if item.title else None,
                    published_at=item.published_at,
                    retrieved_at=retrieved_at,
                    metadata={
                        "connector_name": self.name,
                        "provider": self.provider.name,
                        "external_id": item.external_id[:500] if item.external_id else None,
                        "snippet": item.snippet[:2000] if item.snippet else None,
                        "rank": item.rank or rank,
                    },
                )
            )
        return ConnectorOutput(
            connector=self.name,
            sources=artifacts,
            result_count=len(artifacts),
            metadata={
                "provider": self.provider.name,
                "query_hash": query_hash,
                "cache_hit": cache_hit,
                "invalid_result_count": invalid_count,
            },
        )
