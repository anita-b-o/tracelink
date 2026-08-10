from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from tracelink.connectors.cache import ConnectorCache
from tracelink.connectors.http import get_research_http_client
from tracelink.connectors.protocols import ResearchConnector
from tracelink.connectors.providers import DisabledWebSearchProvider, FakeWebSearchProvider
from tracelink.connectors.public_html import PublicHtmlConnector
from tracelink.connectors.rate_limit import ConnectorRateLimiter
from tracelink.connectors.rdap import RDAPConnector
from tracelink.connectors.url_ingestion import UrlIngestionConnector
from tracelink.connectors.url_safety import UrlSafetyValidator
from tracelink.connectors.web_search import GenericWebSearchConnector
from tracelink.core.config import Settings, get_settings
from tracelink.domain.enums import ResearchTaskType
from tracelink.infrastructure.redis import get_redis_client


async def _test_public_resolver(host: str, port: int) -> Sequence[str]:
    _ = (host, port)
    return ("93.184.216.34",)


class ConnectorRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, ResearchConnector] = {}
        self._by_task_type: dict[ResearchTaskType, ResearchConnector] = {}

    def register(self, connector: ResearchConnector) -> None:
        if connector.name in self._by_name:
            raise ValueError(f"connector already registered: {connector.name}")
        for task_type in connector.supported_task_types:
            if task_type in self._by_task_type:
                raise ValueError(f"connector already registered for task type: {task_type.value}")
        self._by_name[connector.name] = connector
        for task_type in connector.supported_task_types:
            self._by_task_type[task_type] = connector

    def get_connector(self, name: str) -> ResearchConnector:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise LookupError(f"unknown connector: {name}") from exc

    def connectors_for_task_type(
        self, task_type: ResearchTaskType
    ) -> tuple[ResearchConnector, ...]:
        connector = self._by_task_type.get(task_type)
        return (connector,) if connector is not None else ()


def build_connector_registry(settings: Settings | None = None) -> ConnectorRegistry:
    configured = settings or get_settings()
    redis = get_redis_client()
    http = get_research_http_client()
    html = PublicHtmlConnector(http)
    provider = (
        FakeWebSearchProvider() if configured.environment == "test" else DisabledWebSearchProvider()
    )
    registry = ConnectorRegistry()
    for connector in (
        html,
        UrlIngestionConnector(html),
        RDAPConnector(http),
        GenericWebSearchConnector(
            provider,
            configured,
            ConnectorCache(redis, configured.research_cache_ttl_seconds),
            ConnectorRateLimiter(redis),
            UrlSafetyValidator(resolver=_test_public_resolver)
            if configured.environment == "test"
            else None,
        ),
    ):
        registry.register(connector)
    return registry


@lru_cache
def get_connector_registry() -> ConnectorRegistry:
    return build_connector_registry()
