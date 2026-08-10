import pytest

from tracelink.connectors.rate_limit import ConnectorRateLimiter, build_rate_limit_key


class FakeRedis:
    def __init__(self, replies: list[int]) -> None:
        self.replies = replies
        self.calls = 0

    async def eval(self, script: str, numkeys: int, *values: str) -> int:
        _ = (script, numkeys, values)
        reply = self.replies[self.calls]
        self.calls += 1
        return reply


def test_rate_limit_key_hides_source() -> None:
    key = build_rate_limit_key("rdap", "sensitive.example")
    assert key.startswith("tracelink:research:v1:rate:rdap:")
    assert "sensitive" not in key


@pytest.mark.asyncio
async def test_rate_limiter_waits_and_reacquires() -> None:
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        waits.append(delay)

    redis = FakeRedis([250, 0])
    limiter = ConnectorRateLimiter(redis, sleep=sleep)  # type: ignore[arg-type]
    await limiter.acquire("rdap", "example.com", 1)
    assert redis.calls == 2
    assert waits == [0.25]
