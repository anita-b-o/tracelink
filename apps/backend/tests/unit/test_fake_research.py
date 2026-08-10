import pytest

from tracelink.domain.enums import FakeResearchMode, ResearchTaskStatus, ResearchTaskType
from tracelink.domain.models import ResearchTask
from tracelink.services.fake_research import (
    FakeResearchCancelled,
    FakeResearchError,
    FakeResearchExecutor,
)

pytestmark = pytest.mark.asyncio


def task(attempts: int = 1) -> ResearchTask:
    return ResearchTask(
        type=ResearchTaskType.IDENTIFY_ENTITY,
        status=ResearchTaskStatus.RUNNING,
        query="Query",
        attempts=attempts,
    )


async def not_cancelled() -> bool:
    return False


@pytest.mark.parametrize("mode", [FakeResearchMode.SUCCESS, FakeResearchMode.SLOW])
async def test_fake_executor_success_modes(mode: FakeResearchMode) -> None:
    result = await FakeResearchExecutor(0).execute(task(), mode=mode, is_cancelled=not_cancelled)
    assert result["connector"] == "fake_research"
    assert result["metadata"]["task_type"] == ResearchTaskType.IDENTIFY_ENTITY.value


async def test_fake_executor_fail_once_is_deterministic() -> None:
    executor = FakeResearchExecutor(0)
    with pytest.raises(FakeResearchError):
        await executor.execute(
            task(attempts=1), mode=FakeResearchMode.FAIL_ONCE, is_cancelled=not_cancelled
        )
    result = await executor.execute(
        task(attempts=2), mode=FakeResearchMode.FAIL_ONCE, is_cancelled=not_cancelled
    )
    assert result["metadata"]["attempt"] == 2


async def test_fake_executor_always_fail() -> None:
    with pytest.raises(FakeResearchError):
        await FakeResearchExecutor(0).execute(
            task(), mode=FakeResearchMode.ALWAYS_FAIL, is_cancelled=not_cancelled
        )


async def test_fake_executor_checks_cancellation() -> None:
    async def cancelled() -> bool:
        return True

    with pytest.raises(FakeResearchCancelled):
        await FakeResearchExecutor(0).execute(
            task(), mode=FakeResearchMode.SUCCESS, is_cancelled=cancelled
        )
