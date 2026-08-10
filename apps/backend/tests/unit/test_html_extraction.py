from datetime import UTC, datetime

from tracelink.connectors.html import extract_html
from tracelink.connectors.models import ConnectorFetchResult


def test_extract_html_removes_noise_and_collects_metadata() -> None:
    fetch = ConnectorFetchResult(
        url="https://example.com/report",
        status_code=200,
        content_type="text/html",
        text="""
        <html lang="es"><head><title> Reporte  Público </title>
        <link rel="canonical" href="/canonical#fragment">
        <meta name="description" content="A public report">
        <meta property="article:published_time" content="2026-08-10T12:00:00Z">
        <style>hidden css</style><script>hidden script</script></head>
        <body><!-- hidden comment --><nav>menu</nav><main>Hello   world
        <a href="/one#x">One</a><a href="/one">Duplicate</a>
        <a href="javascript:bad">Bad</a></main><footer>footer</footer></body></html>
        """,
        retrieved_at=datetime.now(UTC),
    )

    extracted = extract_html(fetch)

    assert extracted.title == "Reporte Público"
    assert extracted.visible_text == "Reporte Público Hello world One Duplicate Bad"
    assert "hidden" not in extracted.visible_text
    assert extracted.canonical_url == "https://example.com/canonical"
    assert extracted.description == "A public report"
    assert extracted.language == "es"
    assert extracted.published_at == datetime(2026, 8, 10, 12, tzinfo=UTC)
    assert extracted.outgoing_links == ["https://example.com/one"]


def test_extract_plain_text_only_normalizes_whitespace() -> None:
    fetch = ConnectorFetchResult(
        url="https://example.com/plain",
        status_code=200,
        content_type="text/plain",
        text="one\n\n two",
        retrieved_at=datetime.now(UTC),
    )
    assert extract_html(fetch).visible_text == "one two"
