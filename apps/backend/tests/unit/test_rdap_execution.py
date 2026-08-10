import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tracelink.connectors.models import ConnectorContext, ConnectorFetchResult
from tracelink.connectors.rdap import IANA_RDAP_BOOTSTRAP_URL, RDAPConnector


class FixtureHttp:
    async def fetch(self, url: str, **kwargs: object) -> ConnectorFetchResult:
        _ = kwargs
        if url == IANA_RDAP_BOOTSTRAP_URL:
            payload = {"version": "1.0", "services": [[["com"], ["https://rdap.test/"]]]}
            content_type = "application/json"
        else:
            payload = {
                "objectClassName": "domain",
                "ldhName": "EXAMPLE.COM",
                "handle": "EXAMPLE",
                "status": ["active"],
                "nameservers": [{"ldhName": "A.IANA-SERVERS.NET"}],
                "events": [{"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"}],
                "entities": [
                    {
                        "handle": "376",
                        "roles": ["registrar"],
                        "vcardArray": ["vcard", [["fn", {}, "text", "Example Registrar"]]],
                    }
                ],
            }
            content_type = "application/rdap+json"
        text = json.dumps(payload)
        return ConnectorFetchResult(
            url=url,
            status_code=200,
            content_type=content_type,
            text=text,
            retrieved_at=datetime.now(UTC),
            metadata={"content_length": len(text)},
        )


@pytest.mark.asyncio
async def test_rdap_fixture_produces_structured_source_and_raw_document() -> None:
    connector = RDAPConnector(FixtureHttp())  # type: ignore[arg-type]
    output = await connector.execute("example.com", ConnectorContext(investigation_id=uuid4()))
    assert output.result_count == 1
    assert output.metadata["domain_name"] == "EXAMPLE.COM"
    assert output.metadata["registrar"] == "Example Registrar"
    assert output.metadata["nameservers"] == ["A.IANA-SERVERS.NET"]
    assert output.sources[0].source_type == "rdap"
    assert json.loads(output.documents[0].raw_text)["handle"] == "EXAMPLE"
