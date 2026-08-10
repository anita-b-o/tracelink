from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from tracelink.connectors.html import extract_html
from tracelink.connectors.http import ResearchHttpClient
from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorFetchResult,
    ConnectorOutput,
    DocumentArtifact,
    SourceArtifact,
)
from tracelink.connectors.url_safety import normalize_url
from tracelink.domain.enums import ResearchTaskType

HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})


class PublicHtmlConnector:
    name = "public_html"
    supported_task_types: frozenset[ResearchTaskType] = frozenset()
    requests_per_second: int | None = None

    def __init__(self, http: ResearchHttpClient) -> None:
        self.http = http

    def normalize(self, value: str) -> str:
        return normalize_url(value)

    async def fetch(self, url: str) -> ConnectorFetchResult:
        return await self.http.fetch(
            url,
            connector=self.name,
            allowed_content_types=HTML_CONTENT_TYPES,
            requests_per_second=self.requests_per_second,
        )

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        _ = context
        fetch = await self.fetch(value)
        extracted = extract_html(fetch)
        normalized = normalize_url(fetch.url)
        host = urlsplit(normalized).hostname
        source_metadata: dict[str, Any] = {
            "status_code": fetch.status_code,
            "final_url": normalized,
            "content_length": fetch.metadata.get("content_length"),
            "connector_name": self.name,
        }
        for key in ("etag", "last_modified"):
            if header_value := fetch.metadata.get(key):
                source_metadata[key] = header_value
        document_metadata = {
            **source_metadata,
            "canonical_url": extracted.canonical_url,
            "description": extracted.description,
            "language": extracted.language,
            "outgoing_links": extracted.outgoing_links,
            **extracted.metadata,
        }
        return ConnectorOutput(
            connector=self.name,
            sources=[
                SourceArtifact(
                    source_type="web_page",
                    url=fetch.url,
                    normalized_url=normalized,
                    publisher=host,
                    title=extracted.title[:500] if extracted.title else None,
                    published_at=extracted.published_at,
                    retrieved_at=fetch.retrieved_at,
                    metadata=source_metadata,
                )
            ],
            documents=[
                DocumentArtifact(
                    source_normalized_url=normalized,
                    mime_type=fetch.content_type,
                    raw_text=extracted.visible_text,
                    metadata=document_metadata,
                )
            ],
            result_count=1,
            metadata={
                "cache_hit": fetch.cache_hit,
                "retry_count": fetch.retry_count,
            },
        )
