import os
from uuid import uuid4

import pytest

from tracelink.connectors.errors import ConnectorFetchError, ConnectorTimeoutError
from tracelink.connectors.http import get_research_http_client
from tracelink.connectors.models import ConnectorContext
from tracelink.connectors.registry import get_connector_registry
from tracelink.infrastructure.redis import clear_redis_clients

pytestmark = [pytest.mark.real_smoke, pytest.mark.asyncio]


@pytest.mark.skipif(
    os.getenv("RUN_REAL_RESEARCH_SMOKE") != "1",
    reason="set RUN_REAL_RESEARCH_SMOKE=1 to enable public Internet smoke tests",
)
async def test_public_html_and_rdap_smoke() -> None:
    # Integration tests use function-scoped event loops; do not reuse loop-bound clients here.
    get_connector_registry.cache_clear()
    get_research_http_client.cache_clear()
    clear_redis_clients()
    registry = get_connector_registry()
    context = ConnectorContext(investigation_id=uuid4())
    try:
        html = await registry.get_connector("url_ingestion").execute(
            "https://example.com/", context
        )
        rdap = await registry.get_connector("rdap").execute("example.com", context)
    except (ConnectorFetchError, ConnectorTimeoutError) as exc:
        pytest.skip(f"BLOCKED: public Internet is unavailable: {exc.public_message}")
    assert html.documents and "Example Domain" in html.documents[0].raw_text
    assert rdap.metadata["domain_name"] == "EXAMPLE.COM"
