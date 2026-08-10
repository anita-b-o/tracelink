from __future__ import annotations

from tracelink.connectors.models import ConnectorContext, ConnectorOutput
from tracelink.connectors.public_html import PublicHtmlConnector
from tracelink.domain.enums import ResearchTaskType


class UrlIngestionConnector:
    name = "url_ingestion"
    supported_task_types: frozenset[ResearchTaskType] = frozenset()
    requests_per_second: int | None = None

    def __init__(self, html_connector: PublicHtmlConnector) -> None:
        self.html_connector = html_connector

    def normalize(self, value: str) -> str:
        return self.html_connector.normalize(value)

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        output = await self.html_connector.execute(value, context)
        output.connector = self.name
        for source in output.sources:
            source.metadata["connector_name"] = self.name
        for document in output.documents:
            document.metadata["connector_name"] = self.name
        return output
