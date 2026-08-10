from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from tracelink.connectors.errors import ConnectorFetchError, ResponseTooLargeError, UnsafeUrlError
from tracelink.connectors.http import ResearchHttpClient
from tracelink.connectors.url_safety import UrlSafetyValidator
from tracelink.core.config import Settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class Handler(BaseHTTPRequestHandler):
    counts: dict[str, int] = {}

    def do_GET(self) -> None:  # noqa: N802
        self.counts[self.path] = self.counts.get(self.path, 0) + 1
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/html")
            self.end_headers()
            return
        if self.path == "/private":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.2:{self.server.server_port}/html")
            self.end_headers()
            return
        if self.path in {"/retry429", "/retry503"} and self.counts[self.path] < 3:
            self.send_response(429 if self.path == "/retry429" else 503)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        if self.path == "/notfound":
            self.send_response(404)
            self.end_headers()
            return
        body = b"x" * 100 if self.path == "/large" else b"<html><title>Local</title>Hello</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)


@pytest.fixture
def local_server() -> Iterator[tuple[str, int]]:
    Handler.counts = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value


class NoWaitRateLimiter:
    async def acquire(self, connector: str, source: str, requests_per_second: int) -> None:
        _ = (connector, source, requests_per_second)


def client(port: int, *, max_bytes: int = 5000) -> ResearchHttpClient:
    async def resolver(host: str, resolved_port: int) -> tuple[str, ...]:
        _ = resolved_port
        return (host,)

    async def sleep(delay: float) -> None:
        _ = delay

    return ResearchHttpClient(
        Settings(research_http_max_response_bytes=max_bytes),
        client=httpx.AsyncClient(follow_redirects=False, trust_env=False),
        validator=UrlSafetyValidator(
            resolver=resolver,
            allowed_test_authorities=frozenset({f"127.0.0.1:{port}"}),
        ),
        cache=MemoryCache(),  # type: ignore[arg-type]
        rate_limiter=NoWaitRateLimiter(),  # type: ignore[arg-type]
        sleep=sleep,
    )


@pytest.mark.parametrize("path", ["/html", "/redirect", "/retry429", "/retry503"])
async def test_controlled_public_html_scenarios(local_server: tuple[str, int], path: str) -> None:
    base_url, port = local_server
    http = client(port)
    result = await http.fetch(
        f"{base_url}{path}",
        connector="test_html",
        allowed_content_types=frozenset({"text/html"}),
    )
    await http.close()
    assert result.status_code == 200
    assert "Local" in result.text


async def test_controlled_redirect_to_private_is_blocked(
    local_server: tuple[str, int],
) -> None:
    base_url, port = local_server
    http = client(port)
    with pytest.raises(UnsafeUrlError):
        await http.fetch(
            f"{base_url}/private",
            connector="test_html",
            allowed_content_types=frozenset({"text/html"}),
        )
    await http.close()


async def test_controlled_size_404_and_cache(
    local_server: tuple[str, int],
) -> None:
    base_url, port = local_server
    http = client(port, max_bytes=20)
    with pytest.raises(ResponseTooLargeError):
        await http.fetch(
            f"{base_url}/large",
            connector="test_html",
            allowed_content_types=frozenset({"text/html"}),
        )
    with pytest.raises(ConnectorFetchError):
        await http.fetch(
            f"{base_url}/notfound",
            connector="test_html",
            allowed_content_types=frozenset({"text/html"}),
        )
    assert Handler.counts["/notfound"] == 1
    await http.close()

    http = client(port)
    first = await http.fetch(
        f"{base_url}/html",
        connector="test_html",
        allowed_content_types=frozenset({"text/html"}),
    )
    second = await http.fetch(
        f"{base_url}/html",
        connector="test_html",
        allowed_content_types=frozenset({"text/html"}),
    )
    await http.close()
    assert first.cache_hit is False and second.cache_hit is True
    assert Handler.counts["/html"] == 1
