import asyncio
from collections.abc import Awaitable, Callable

from tracelink.domain.enums import FakeResearchMode
from tracelink.domain.models import JsonObject, ResearchTask

CancellationCheck = Callable[[], Awaitable[bool]]


class FakeResearchError(RuntimeError):
    code = "FAKE_RESEARCH_FAILED"


class FakeResearchCancelled(RuntimeError):
    pass


class FakeResearchExecutor:
    def __init__(self, delay_ms: int) -> None:
        self.delay_ms = delay_ms

    async def execute(
        self,
        research_task: ResearchTask,
        *,
        mode: FakeResearchMode = FakeResearchMode.SUCCESS,
        is_cancelled: CancellationCheck,
    ) -> JsonObject:
        multiplier = 20 if mode is FakeResearchMode.SLOW else 1
        remaining = max(self.delay_ms * multiplier, 0) / 1000
        while remaining > 0:
            if await is_cancelled():
                raise FakeResearchCancelled
            interval = min(remaining, 0.05)
            await asyncio.sleep(interval)
            remaining -= interval
        if await is_cancelled():
            raise FakeResearchCancelled
        if mode is FakeResearchMode.ALWAYS_FAIL or (
            mode is FakeResearchMode.FAIL_ONCE and research_task.attempts == 1
        ):
            raise FakeResearchError(f"simulated failure for {research_task.type.value}")
        return {
            "kind": "fake_research",
            "task_type": research_task.type.value,
            "attempt": research_task.attempts,
            "summary": f"Simulated {research_task.type.value.lower()} result",
            "items": [],
        }
