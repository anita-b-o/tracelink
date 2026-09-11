from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from tracelink.connectors.errors import (
    ConnectorTimeoutError,
    UnsupportedContentTypeError,
    WebSearchConfigurationError,
)
from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorOutput,
    ConnectorSearchResult,
    DocumentArtifact,
    SourceArtifact,
)
from tracelink.connectors.providers import DisabledWebSearchProvider, FakeWebSearchProvider
from tracelink.connectors.url_safety import UrlSafetyValidator
from tracelink.connectors.web_search import GenericWebSearchConnector
from tracelink.core.config import Settings
from tracelink.domain.enums import ResearchTaskType


class MemoryCache:
    instances: list["MemoryCache"] = []

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.instances.append(self)

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.values.get(key)

    async def set(self, key: str, value: str) -> None:
        self.set_calls += 1
        self.values[key] = value


class RateLimiter:
    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self, *args: Any) -> None:
        _ = args
        self.calls += 1


class RecordingHtmlConnector:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.error = error

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        _ = context
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return ConnectorOutput(connector="public_html")


class SuccessfulHtmlConnector(RecordingHtmlConnector):
    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        self.calls.append(value)
        return ConnectorOutput(
            connector="public_html",
            sources=[
                SourceArtifact(
                    source_type="web_page",
                    url=value,
                    normalized_url=value,
                    title="HTML title",
                    retrieved_at=datetime.now(UTC),
                    metadata={"final_url": value, "status_code": 200},
                )
            ],
            documents=[
                DocumentArtifact(
                    source_normalized_url=value,
                    mime_type="text/html",
                    raw_text="HTML body",
                    metadata={"description": "HTML description"},
                )
            ],
            result_count=1,
        )


async def public_resolver(host: str, port: int) -> tuple[str, ...]:
    _ = (host, port)
    return ("93.184.216.34",)


def connector(provider: Any) -> tuple[GenericWebSearchConnector, RateLimiter]:
    limiter = RateLimiter()
    return (
        GenericWebSearchConnector(
            provider,
            Settings(environment="test"),
            MemoryCache(),  # type: ignore[arg-type]
            limiter,  # type: ignore[arg-type]
            UrlSafetyValidator(resolver=public_resolver),
        ),
        limiter,
    )


@pytest.mark.asyncio
async def test_disabled_provider_fails_explicitly() -> None:
    search, limiter = connector(DisabledWebSearchProvider())
    with pytest.raises(WebSearchConfigurationError):
        await search.execute(
            "Acme",
            ConnectorContext(investigation_id=uuid4(), task_type=ResearchTaskType.WEB_SEARCH),
        )
    assert limiter.calls == 0


@pytest.mark.asyncio
async def test_search_deduplicates_urls_without_caching_serp() -> None:
    serp_primary_title = "SERP_TITLE_PRIMARY_SHOULD_NOT_PERSIST"
    serp_duplicate_title = "SERP_TITLE_DUPLICATE_SHOULD_NOT_PERSIST"
    serp_primary_snippet = "SERP_SNIPPET_PRIMARY_SHOULD_NOT_PERSIST"
    serp_duplicate_snippet = "SERP_SNIPPET_DUPLICATE_SHOULD_NOT_PERSIST"
    serp_primary_external_id = "SERP_EXTERNAL_ID_PRIMARY_SHOULD_NOT_PERSIST"
    serp_duplicate_external_id = "SERP_EXTERNAL_ID_DUPLICATE_SHOULD_NOT_PERSIST"
    serp_primary_rank = 987654321
    serp_duplicate_rank = 987654322
    provider = FakeWebSearchProvider(
        [
            ConnectorSearchResult(
                url="https://EXAMPLE.com/a#one",
                title=serp_primary_title,
                snippet=serp_primary_snippet,
                external_id=serp_primary_external_id,
                rank=serp_primary_rank,
            ),
            ConnectorSearchResult(
                url="https://example.com/a",
                title=serp_duplicate_title,
                snippet=serp_duplicate_snippet,
                external_id=serp_duplicate_external_id,
                rank=serp_duplicate_rank,
            ),
        ]
    )
    search, limiter = connector(provider)
    html = SuccessfulHtmlConnector()
    search.html_connector = html  # type: ignore[assignment]
    context = ConnectorContext(investigation_id=uuid4(), task_type=ResearchTaskType.PUBLIC_MENTIONS)
    first = await search.execute("Acme Corp", context)
    second = await search.execute("Acme Corp", context)
    assert first.result_count == 1
    assert first.metadata["duplicate_result_count"] == 1
    assert first.sources[0].title == "HTML title"
    assert first.sources[0].metadata == {"final_url": "https://example.com/a", "status_code": 200}
    assert first.documents[0].metadata["description"] == "HTML description"
    persisted = str(first.model_dump())
    for serp_value in (
        serp_primary_title,
        serp_duplicate_title,
        serp_primary_snippet,
        serp_duplicate_snippet,
        serp_primary_external_id,
        serp_duplicate_external_id,
        str(serp_primary_rank),
        str(serp_duplicate_rank),
    ):
        assert serp_value not in persisted
    assert second.result_count == 1
    assert limiter.calls == 2
    assert MemoryCache.instances[-1].get_calls == 0
    assert MemoryCache.instances[-1].set_calls == 0


@pytest.mark.asyncio
async def test_private_search_result_is_persistable_but_never_fetched() -> None:
    provider = FakeWebSearchProvider(
        [ConnectorSearchResult(url="http://localhost/private", title="unsafe")]
    )
    html = RecordingHtmlConnector()
    search, _ = connector(provider)
    search.html_connector = html  # type: ignore[assignment]

    output = await search.execute(
        "Acme", ConnectorContext(investigation_id=uuid4(), task_type=ResearchTaskType.WEB_SEARCH)
    )

    assert output.sources == []
    assert output.documents == []
    assert html.calls == []
    assert output.metadata["failure_reasons"] == {"UNSAFE_URL": 1}


@pytest.mark.asyncio
async def test_unsupported_fetch_is_reported_without_hiding_search_success() -> None:
    provider = FakeWebSearchProvider(
        [ConnectorSearchResult(url="https://example.com/file.pdf", title="PDF")]
    )
    html = RecordingHtmlConnector(UnsupportedContentTypeError(status_code=200))
    search, _ = connector(provider)
    search.html_connector = html  # type: ignore[assignment]

    output = await search.execute(
        "Acme", ConnectorContext(investigation_id=uuid4(), task_type=ResearchTaskType.WEB_SEARCH)
    )

    assert output.status == "success"
    assert output.result_count == 0
    assert output.metadata["document_count"] == 0
    assert output.metadata["failure_reasons"] == {"UNSUPPORTED_CONTENT_TYPE": 1}


@pytest.mark.asyncio
async def test_fetch_network_failure_is_not_converted_to_completed() -> None:
    provider = FakeWebSearchProvider(
        [ConnectorSearchResult(url="https://example.com/profile", title="Profile")]
    )
    html = RecordingHtmlConnector(ConnectorTimeoutError())
    search, _ = connector(provider)
    search.html_connector = html  # type: ignore[assignment]

    output = await search.execute(
        "Acme", ConnectorContext(investigation_id=uuid4(), task_type=ResearchTaskType.WEB_SEARCH)
    )

    assert output.status == "failed"
    assert output.sources == []
    assert output.metadata["error_code"] == "CONNECTOR_TIMEOUT"
