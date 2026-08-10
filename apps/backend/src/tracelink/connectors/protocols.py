from __future__ import annotations

from typing import Protocol

from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorFetchResult,
    ConnectorOutput,
    ConnectorSearchResult,
)
from tracelink.domain.enums import ResearchTaskType


class ResearchConnector(Protocol):
    name: str
    supported_task_types: frozenset[ResearchTaskType]
    requests_per_second: int | None

    def normalize(self, value: str) -> str: ...

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput: ...


class SearchConnector(ResearchConnector, Protocol):
    async def search(self, query: str, limit: int) -> list[ConnectorSearchResult]: ...


class FetchConnector(ResearchConnector, Protocol):
    async def fetch(self, url: str) -> ConnectorFetchResult: ...
