from __future__ import annotations

from collections.abc import Awaitable, Callable

from tracelink.connectors.errors import InvalidConnectorInputError
from tracelink.connectors.models import ConnectorContext, ConnectorOutput
from tracelink.connectors.registry import ConnectorRegistry
from tracelink.domain.enums import ResearchTaskType
from tracelink.domain.models import ResearchTask
from tracelink.services.fake_research import FakeResearchCancelled

CancellationCheck = Callable[[], Awaitable[bool]]


class ConnectorResearchExecutor:
    def __init__(self, registry: ConnectorRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        task: ResearchTask,
        *,
        is_cancelled: CancellationCheck,
    ) -> ConnectorOutput:
        if await is_cancelled():
            raise FakeResearchCancelled
        if task.type is ResearchTaskType.IDENTIFY_ENTITY:
            return ConnectorOutput(
                connector="fake_research",
                status="skipped",
                metadata={"reason": "deferred_to_phase_4"},
            )
        connectors = self.registry.connectors_for_task_type(task.type)
        if not connectors:
            return ConnectorOutput(
                connector="none",
                status="skipped",
                metadata={"reason": "no_connector_for_task_type"},
            )
        connector = connectors[0]
        try:
            normalized = connector.normalize(task.query)
        except InvalidConnectorInputError:
            if task.type is ResearchTaskType.DOMAIN_LOOKUP:
                return ConnectorOutput(
                    connector=connector.name,
                    status="skipped",
                    metadata={"reason": "query_is_not_a_domain"},
                )
            raise
        output = await connector.execute(
            normalized,
            ConnectorContext(
                investigation_id=task.investigation_id,
                research_task_id=task.id,
                task_type=task.type,
            ),
        )
        if await is_cancelled():
            raise FakeResearchCancelled
        return output
