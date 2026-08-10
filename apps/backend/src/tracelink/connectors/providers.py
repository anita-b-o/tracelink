from __future__ import annotations

import hashlib
from typing import Protocol

from tracelink.connectors.models import ConnectorSearchResult


class WebSearchProvider(Protocol):
    name: str
    enabled: bool

    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]: ...


class DisabledWebSearchProvider:
    name = "disabled"
    enabled = False

    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]:
        _ = (query, limit)
        return []


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
