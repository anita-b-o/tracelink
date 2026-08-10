from tracelink.connectors.models import ConnectorContext, ConnectorOutput
from tracelink.connectors.registry import ConnectorRegistry
from tracelink.domain.enums import ResearchTaskType


class StubConnector:
    name = "stub"
    supported_task_types = frozenset({ResearchTaskType.WEB_SEARCH})
    requests_per_second = None

    def normalize(self, value: str) -> str:
        return value

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        _ = (value, context)
        return ConnectorOutput(connector=self.name)


def test_registry_resolves_by_name_and_task_type() -> None:
    registry = ConnectorRegistry()
    connector = StubConnector()
    registry.register(connector)
    assert registry.get_connector("stub") is connector
    assert registry.connectors_for_task_type(ResearchTaskType.WEB_SEARCH) == (connector,)


def test_registry_rejects_duplicate_name_and_task_mapping() -> None:
    registry = ConnectorRegistry()
    registry.register(StubConnector())
    try:
        registry.register(StubConnector())
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate connector was accepted")
