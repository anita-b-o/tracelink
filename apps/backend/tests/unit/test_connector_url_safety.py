import pytest

from tracelink.connectors.errors import UnsafeUrlError
from tracelink.connectors.url_safety import UrlSafetyValidator, normalize_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTPS://Example.COM:443", "https://example.com/"),
        ("http://example.com:80/path#part", "http://example.com/path"),
        ("https://example.com/path/?b=2&a=1", "https://example.com/path/?b=2&a=1"),
        ("https://bücher.example/", "https://xn--bcher-kva.example/"),
    ],
)
def test_normalize_url_is_conservative(value: str, expected: str) -> None:
    assert normalize_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "data:text/plain,value",
        "javascript:alert(1)",
        "https://user:secret@example.com/",
        "https://bad_host.example/",
    ],
)
def test_normalize_url_rejects_unsafe_syntax(value: str) -> None:
    with pytest.raises(UnsafeUrlError):
        normalize_url(value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.1.2",
        "169.254.169.254",
        "100.100.100.200",
    ],
)
async def test_validator_blocks_non_public_addresses(address: str) -> None:
    async def resolver(host: str, port: int) -> tuple[str, ...]:
        _ = (host, port)
        return (address,)

    with pytest.raises(UnsafeUrlError):
        await UrlSafetyValidator(resolver=resolver).validate("https://public.example/")


@pytest.mark.asyncio
async def test_validator_fails_closed_for_mixed_dns_answers() -> None:
    async def resolver(host: str, port: int) -> tuple[str, ...]:
        _ = (host, port)
        return ("93.184.216.34", "127.0.0.1")

    with pytest.raises(UnsafeUrlError):
        await UrlSafetyValidator(resolver=resolver).validate("https://public.example/")


@pytest.mark.asyncio
async def test_validator_allows_public_address() -> None:
    async def resolver(host: str, port: int) -> tuple[str, ...]:
        _ = (host, port)
        return ("93.184.216.34",)

    validated = await UrlSafetyValidator(resolver=resolver).validate("https://Example.com")
    assert validated.normalized_url == "https://example.com/"
