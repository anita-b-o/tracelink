import pytest

from tracelink.connectors.errors import InvalidConnectorInputError
from tracelink.connectors.rdap import normalize_domain, select_rdap_base_url


def test_normalize_domain_supports_idna() -> None:
    assert normalize_domain("BÜCHER.example.") == "xn--bcher-kva.example"


@pytest.mark.parametrize("value", ["example", "https://example.com", "example com", "-x.com"])
def test_normalize_domain_rejects_non_domain_input(value: str) -> None:
    with pytest.raises(InvalidConnectorInputError):
        normalize_domain(value)


def test_bootstrap_uses_longest_match_and_https() -> None:
    payload = {
        "services": [
            [["com"], ["http://rdap.example/", "https://rdap.example/"]],
            [["example.com"], ["https://specific.example/rdap/"]],
        ]
    }
    assert select_rdap_base_url(payload, "a.example.com") == "https://specific.example/rdap/"
