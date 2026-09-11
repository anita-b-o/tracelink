from __future__ import annotations

import hashlib

from tracelink.connectors.cache import ConnectorCache
from tracelink.connectors.errors import (
    ConnectorError,
    ConnectorFetchError,
    ResponseTooLargeError,
    UnsafeUrlError,
    UnsupportedContentTypeError,
)
from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorOutput,
    ConnectorSearchResult,
    DocumentArtifact,
    SourceArtifact,
)
from tracelink.connectors.providers import WebSearchProvider
from tracelink.connectors.public_html import PublicHtmlConnector
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
        html_connector: PublicHtmlConnector | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.cache = cache
        self.rate_limiter = rate_limiter
        self.html_connector = html_connector
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

    @staticmethod
    def _controlled_fetch_skip(error: ConnectorError) -> bool:
        if isinstance(
            error,
            (UnsafeUrlError, UnsupportedContentTypeError, ResponseTooLargeError),
        ):
            return True
        return (
            isinstance(error, ConnectorFetchError)
            and error.status_code is not None
            and 400 <= error.status_code < 500
        )

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        query = self.normalize(value)
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        if not self.provider.enabled:
            await self.provider.search(query, 1)
            raise AssertionError("disabled web search provider did not fail")

        provider_query = self._provider_query(query, context.task_type)
        limit = self.settings.research_web_search_max_results
        # Search results are discovery input only. Do not read or write ConnectorCache
        # here: caching the provider response would retain SERP content.
        await self.rate_limiter.acquire(
            self.name,
            self.provider.name,
            self.requests_per_second or self.settings.research_connector_requests_per_second,
        )
        results = await self.search(provider_query, limit)

        candidate_urls: list[str] = []
        seen: set[str] = set()
        invalid_count = 0
        duplicate_count = 0
        for item in results[:limit]:
            try:
                normalized = normalize_url(item.url)
            except ConnectorError:
                invalid_count += 1
                continue
            if normalized in seen:
                duplicate_count += 1
                continue
            seen.add(normalized)
            candidate_urls.append(normalized)

        documents: list[DocumentArtifact] = []
        artifacts: list[SourceArtifact] = []
        fetched_count = 0
        fetch_selected_count = 0
        failure_counts: dict[str, int] = {}
        fatal_fetch_error: ConnectorError | None = None
        if self.html_connector is not None:
            for candidate_url in candidate_urls:
                if fetch_selected_count >= self.settings.research_web_search_fetch_limit:
                    break
                try:
                    await self.validator.validate(candidate_url)
                except ConnectorError as exc:
                    failure_counts[exc.code] = failure_counts.get(exc.code, 0) + 1
                    if not self._controlled_fetch_skip(exc):
                        fatal_fetch_error = fatal_fetch_error or exc
                    continue
                fetch_selected_count += 1
                try:
                    fetched = await self.html_connector.execute(candidate_url, context)
                except ConnectorError as exc:
                    failure_counts[exc.code] = failure_counts.get(exc.code, 0) + 1
                    if not self._controlled_fetch_skip(exc):
                        fatal_fetch_error = fatal_fetch_error or exc
                    continue
                if not fetched.documents:
                    failure_counts["EMPTY_FETCH_OUTPUT"] = (
                        failure_counts.get("EMPTY_FETCH_OUTPUT", 0) + 1
                    )
                    continue
                fetched_source = fetched.sources[0] if fetched.sources else None
                if fetched_source is None:
                    failure_counts["EMPTY_FETCH_OUTPUT"] = (
                        failure_counts.get("EMPTY_FETCH_OUTPUT", 0) + 1
                    )
                    continue
                artifacts.append(fetched_source)
                fetched_count += 1
                for document in fetched.documents:
                    document.source_normalized_url = fetched_source.normalized_url
                    documents.append(document)
        return ConnectorOutput(
            connector=self.name,
            status="failed" if fatal_fetch_error is not None else "success",
            sources=artifacts,
            documents=documents,
            result_count=len(artifacts),
            metadata={
                "provider": self.provider.name,
                "query_hash": query_hash,
                "search_result_count": len(results),
                "discovered_count": len(candidate_urls),
                "source_count": len(artifacts),
                "fetch_selected_count": fetch_selected_count,
                "fetched_count": fetched_count,
                "document_count": len(documents),
                "entity_count": None,
                "entity_count_status": "downstream" if documents else "not_applicable",
                "skipped_count": invalid_count + sum(failure_counts.values()),
                "fetch_skipped_count": max(0, len(results) - fetched_count),
                "failure_reasons": failure_counts,
                **(
                    {
                        "error_code": fatal_fetch_error.code,
                        "error_message": fatal_fetch_error.public_message,
                    }
                    if fatal_fetch_error is not None
                    else {}
                ),
                "invalid_result_count": invalid_count,
                "duplicate_result_count": duplicate_count,
            },
        )
