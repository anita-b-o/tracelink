import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from tracelink.connectors.models import ConnectorOutput, DocumentArtifact, SourceArtifact
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
    ) -> JsonObject | ConnectorOutput:
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
        if mode is FakeResearchMode.PIPELINE_SUCCESS:
            url = f"https://fixture.tracelink.invalid/{research_task.id}"
            return ConnectorOutput(
                connector="fake_relationship_pipeline",
                sources=[
                    SourceArtifact(
                        source_type="fixture",
                        url=url,
                        normalized_url=url,
                        publisher="fixture.tracelink.invalid",
                        retrieved_at=datetime.now(UTC),
                        metadata={"quality_score": 1.0, "hermetic": True},
                    )
                ],
                documents=[
                    DocumentArtifact(
                        source_normalized_url=url,
                        mime_type="text/plain",
                        raw_text="Dr. Juan Pérez fue designado director de ACME S.A.",
                        metadata={"hermetic": True},
                    )
                ],
                result_count=1,
                metadata={"hermetic": True},
            )
        return {
            "connector": "fake_research",
            "status": "success",
            "source_ids": [],
            "document_ids": [],
            "result_count": 0,
            "metadata": {
                "task_type": research_task.type.value,
                "attempt": research_task.attempts,
                "simulated": True,
            },
        }
