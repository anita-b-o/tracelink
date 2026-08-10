from typing import Any
from uuid import uuid4

import pytest

from tracelink.connectors.models import ConnectorContext, ConnectorSearchResult
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
async def test_disabled_provider_is_skipped() -> None:
    search, limiter = connector(DisabledWebSearchProvider())
    output = await search.execute(
        "Acme", ConnectorContext(investigation_id=uuid4(), task_type=ResearchTaskType.WEB_SEARCH)
    )
    assert output.status == "skipped"
    assert output.sources == []
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
