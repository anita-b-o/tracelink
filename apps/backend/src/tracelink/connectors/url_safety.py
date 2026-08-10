from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit, urlunsplit

from tracelink.connectors.errors import UnsafeUrlError

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]

BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "instance-data",
    }
)
BLOCKED_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("168.63.129.16"),
    }
)


def _validate_domain(host: str) -> str:
    try:
        ascii_host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UnsafeUrlError() from exc
    if not ascii_host or len(ascii_host) > 253:
        raise UnsafeUrlError()
    for label in ascii_host.split("."):
        if not label or len(label) > 63:
            raise UnsafeUrlError()
        if label.startswith("-") or label.endswith("-"):
            raise UnsafeUrlError()
        if not all(character.isalnum() or character == "-" for character in label):
            raise UnsafeUrlError()
    return ascii_host


def normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError() from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError()
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError()

    host_value = parsed.hostname.rstrip(".")
    try:
        ip = ipaddress.ip_address(host_value)
    except ValueError:
        host = _validate_domain(host_value)
    else:
        host = ip.compressed
        if ip.version == 6:
            host = f"[{host}]"

    if port is not None and not 1 <= port <= 65535:
        raise UnsafeUrlError()
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    normalized = SplitResult(scheme, netloc, path, parsed.query, "")
    return urlunsplit(normalized)


def _unsafe_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return ip in BLOCKED_IPS or not ip.is_global


async def system_resolver(host: str, port: int) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    try:
        records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError("the URL hostname could not be resolved") from exc
    return tuple(dict.fromkeys(str(record[4][0]) for record in records))


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    normalized_url: str
    host: str
    port: int
    addresses: tuple[str, ...]


class UrlSafetyValidator:
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        allowed_test_authorities: frozenset[str] = frozenset(),
    ) -> None:
        self.resolver = resolver
        self.allowed_test_authorities = allowed_test_authorities

    async def validate(self, value: str) -> ValidatedUrl:
        normalized = normalize_url(value)
        parsed = urlsplit(normalized)
        assert parsed.hostname is not None
        host = parsed.hostname.lower().rstrip(".")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        authority = f"{host}:{port}"
        if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
            raise UnsafeUrlError()

        addresses = tuple(await self.resolver(host, port))
        if not addresses:
            raise UnsafeUrlError("the URL hostname could not be resolved")
        if authority not in self.allowed_test_authorities and any(
            _unsafe_ip(address) for address in addresses
        ):
            raise UnsafeUrlError()
        return ValidatedUrl(normalized, host, port, addresses)
