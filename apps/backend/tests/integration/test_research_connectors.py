from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.connectors.errors import ConnectorFetchError
from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorOutput,
    DocumentArtifact,
    SourceArtifact,
)
from tracelink.connectors.registry import ConnectorRegistry, get_connector_registry
from tracelink.core.config import get_settings
from tracelink.domain.enums import ResearchTaskStatus, ResearchTaskType
from tracelink.domain.models import Document, Source
from tracelink.infrastructure.database import get_session
from tracelink.jobs.research import execute_research_task_async
from tracelink.main import app
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.research_artifacts import ResearchArtifactService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class ArtifactConnector:
    requests_per_second = None

    def __init__(self, name: str, task_type: ResearchTaskType) -> None:
        self.name = name
        self.supported_task_types = frozenset({task_type})

    def normalize(self, value: str) -> str:
        return value

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        normalized_url = f"https://example.com/{self.name}"
        retrieved_at = datetime.now(UTC)
        return ConnectorOutput(
            connector=self.name,
            sources=[
                SourceArtifact(
                    source_type="web_page" if self.name == "web_search" else "rdap",
                    url=normalized_url,
                    normalized_url=normalized_url,
                    title=value,
                    retrieved_at=retrieved_at,
                    metadata={"connector_name": self.name},
                )
            ],
            documents=(
                [
                    DocumentArtifact(
                        source_normalized_url=normalized_url,
                        mime_type="application/rdap+json",
                        raw_text='{"domain":"example.com"}',
                        metadata={"connector_name": self.name},
                    )
                ]
                if self.name == "rdap"
                else []
            ),
            result_count=1,
        )


class FailingConnector(ArtifactConnector):
    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        _ = (value, context)
        raise ConnectorFetchError(status_code=503)


class UrlConnector(ArtifactConnector):
    def __init__(self) -> None:
        self.name = "url_ingestion"
        self.supported_task_types: frozenset[ResearchTaskType] = frozenset()


def workflow_registry(*, fail_web: bool = False) -> ConnectorRegistry:
    registry = ConnectorRegistry()
    web_type = FailingConnector if fail_web else ArtifactConnector
    registry.register(web_type("web_search", ResearchTaskType.WEB_SEARCH))
    registry.register(ArtifactConnector("public_mentions", ResearchTaskType.PUBLIC_MENTIONS))
    registry.register(ArtifactConnector("rdap", ResearchTaskType.DOMAIN_LOOKUP))
    return registry


async def create_task(
    session: AsyncSession, task_type: ResearchTaskType, query: str = "example.com"
) -> UUID:
    investigation = await InvestigationRepository(session).create("Research", query)
    await InvestigationWorkflowService(session, get_settings()).start(investigation.id)
    await session.commit()
    tasks = await ResearchTaskRepository(session).list_by_investigation(investigation.id)
    return next(task.id for task in tasks if task.type is task_type)


async def test_artifact_persistence_deduplicates_source_and_document(
    db_session: AsyncSession,
) -> None:
    connector = ArtifactConnector("rdap", ResearchTaskType.DOMAIN_LOOKUP)
    output = await connector.execute("example.com", ConnectorContext(investigation_id=UUID(int=1)))
    service = ResearchArtifactService(db_session)
    first = await service.persist(output)
    second = await service.persist(output)
    assert first.source_ids == second.source_ids
    assert first.document_ids == second.document_ids
    assert await db_session.scalar(select(func.count()).select_from(Source)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 1


@pytest.mark.parametrize("task_type", [ResearchTaskType.WEB_SEARCH, ResearchTaskType.DOMAIN_LOOKUP])
async def test_research_task_uses_connector_and_persists_result(
    db_session: AsyncSession, task_type: ResearchTaskType
) -> None:
    task_id = await create_task(db_session, task_type)
    await execute_research_task_async(
        task_id, f"connector-{task_type.value}", None, workflow_registry()
    )
    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None and task.status is ResearchTaskStatus.COMPLETED
    assert task.result is not None
    assert task.result["status"] == "success"
    assert task.result["source_ids"]
    if task_type is ResearchTaskType.DOMAIN_LOOKUP:
        assert task.result["document_ids"]


async def test_connector_failure_marks_task_failed_with_safe_metadata(
    db_session: AsyncSession,
) -> None:
    task_id = await create_task(db_session, ResearchTaskType.WEB_SEARCH)
    await execute_research_task_async(
        task_id, "connector-failure", None, workflow_registry(fail_web=True)
    )
    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None and task.status is ResearchTaskStatus.FAILED
    assert task.last_error_code == "CONNECTOR_FETCH_FAILED"
    assert task.last_error_message == "the public source could not be fetched"
    assert task.result is not None and task.result["status"] == "failed"


async def test_manual_url_api_returns_persisted_ids(db_session: AsyncSession) -> None:
    investigation = await InvestigationRepository(db_session).create("URL", "query")
    await db_session.commit()
    registry = ConnectorRegistry()
    registry.register(UrlConnector())

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_connector_registry] = lambda: registry
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/investigations/{investigation.id}/sources/url",
                json={"url": "https://example.com/manual"},
            )
        assert response.status_code == 201
        assert response.json()["source_ids"]
    finally:
        app.dependency_overrides.clear()
