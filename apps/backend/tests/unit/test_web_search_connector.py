from typing import Any
from uuid import uuid4

import pytest

from tracelink.connectors.errors import (
    ConnectorTimeoutError,
    UnsupportedContentTypeError,
    WebSearchConfigurationError,
)
from tracelink.connectors.models import ConnectorContext, ConnectorOutput, ConnectorSearchResult
from tracelink.connectors.providers import DisabledWebSearchProvider, FakeWebSearchProvider
from tracelink.connectors.url_safety import UrlSafetyValidator
from tracelink.connectors.web_search import GenericWebSearchConnector
from tracelink.core.config import Settings
from tracelink.domain.enums import ResearchTaskType


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str) -> None:
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
async def test_fake_provider_deduplicates_results_and_cache() -> None:
    provider = FakeWebSearchProvider(
        [
            ConnectorSearchResult(url="https://EXAMPLE.com/a#one", title="A", rank=1),
            ConnectorSearchResult(url="https://example.com/a", title="duplicate", rank=2),
        ]
    )
    search, limiter = connector(provider)
    context = ConnectorContext(investigation_id=uuid4(), task_type=ResearchTaskType.PUBLIC_MENTIONS)
    first = await search.execute("Acme Corp", context)
    second = await search.execute("Acme Corp", context)
    assert first.result_count == 1
    assert first.sources[0].normalized_url == "https://example.com/a"
    assert second.metadata["cache_hit"] is True
    assert limiter.calls == 1


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

    assert len(output.sources) == 1
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
    assert output.result_count == 1
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
    assert len(output.sources) == 1
    assert output.metadata["error_code"] == "CONNECTOR_TIMEOUT"
