from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.connectors.errors import ConnectorFetchError
from tracelink.connectors.http import ResearchHttpClient
from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorOutput,
    DocumentArtifact,
    SourceArtifact,
)
from tracelink.connectors.providers import (
    BraveWebSearchProvider,
    DisabledWebSearchProvider,
    FakeWebSearchProvider,
)
from tracelink.connectors.public_html import PublicHtmlConnector
from tracelink.connectors.registry import ConnectorRegistry, get_connector_registry
from tracelink.connectors.url_safety import UrlSafetyValidator
from tracelink.connectors.web_search import GenericWebSearchConnector
from tracelink.core.config import Settings, get_settings
from tracelink.domain.enums import ResearchTaskStatus, ResearchTaskType
from tracelink.domain.models import Document, Entity, EntityMention, OutboxEvent, Source
from tracelink.infrastructure.database import get_session
from tracelink.jobs.research import execute_research_task_async
from tracelink.main import app
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.research_tasks import ResearchTaskRepository
from tracelink.services.document_entity_processing import DocumentEntityProcessingService
from tracelink.services.investigation_workflow import InvestigationWorkflowService
from tracelink.services.outbox import enqueue_document_entities_once
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


class PartialFailureConnector(ArtifactConnector):
    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        output = await super().execute(value, context)
        output.status = "failed"
        output.metadata = {
            "error_code": "CONNECTOR_TIMEOUT",
            "error_message": "the public source timed out",
        }
        return output


class UrlConnector(ArtifactConnector):
    def __init__(self) -> None:
        self.name = "url_ingestion"
        self.supported_task_types: frozenset[ResearchTaskType] = frozenset()


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


async def public_resolver(host: str, port: int) -> tuple[str, ...]:
    _ = (host, port)
    return ("93.184.216.34",)


def controlled_web_connector() -> tuple[
    GenericWebSearchConnector, httpx.AsyncClient, ResearchHttpClient
]:
    def search_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "test-search-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://profiles.example/recruiter",
                            "title": "Recruiting profile",
                            "description": "Public recruiting profile",
                        }
                    ]
                }
            },
        )

    def html_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://profiles.example/recruiter"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<html><title>Recruiter</title><body>"
                "Dr. Jane Recruiter works for ACME Corp. See acme.example."
                "</body></html>"
            ),
        )

    settings = Settings(app_env="test")
    search_client = httpx.AsyncClient(transport=httpx.MockTransport(search_handler))
    fetch_client = httpx.AsyncClient(transport=httpx.MockTransport(html_handler))
    validator = UrlSafetyValidator(resolver=public_resolver)
    research_http = ResearchHttpClient(
        settings,
        client=fetch_client,
        validator=validator,
        cache=MemoryCache(),  # type: ignore[arg-type]
        rate_limiter=NoWaitRateLimiter(),  # type: ignore[arg-type]
    )
    connector = GenericWebSearchConnector(
        BraveWebSearchProvider(
            SecretStr("test-search-key"),
            settings.web_search_timeout_seconds,
            client=search_client,
        ),
        settings,
        MemoryCache(),  # type: ignore[arg-type]
        NoWaitRateLimiter(),  # type: ignore[arg-type]
        validator=validator,
        html_connector=PublicHtmlConnector(research_http),
    )
    return connector, search_client, research_http


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
    investigation = await InvestigationRepository(db_session).create("Artifacts", "example")
    first = await service.persist(investigation.id, output)
    second = await service.persist(investigation.id, output)
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


async def test_partial_connector_failure_persists_artifacts_and_marks_task_failed(
    db_session: AsyncSession,
) -> None:
    task_id = await create_task(db_session, ResearchTaskType.WEB_SEARCH)
    registry = ConnectorRegistry()
    registry.register(PartialFailureConnector("web_search", ResearchTaskType.WEB_SEARCH))

    await execute_research_task_async(task_id, "partial-failure", None, registry)

    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None and task.status is ResearchTaskStatus.FAILED
    assert task.last_error_code == "CONNECTOR_TIMEOUT"
    assert task.result is not None and task.result["source_ids"]
    assert task.result["status"] == "failed"


async def test_disabled_web_provider_marks_task_failed_not_skipped(
    db_session: AsyncSession,
) -> None:
    task_id = await create_task(db_session, ResearchTaskType.WEB_SEARCH)
    registry = ConnectorRegistry()
    registry.register(
        GenericWebSearchConnector(
            DisabledWebSearchProvider(),
            Settings(app_env="test"),
            MemoryCache(),  # type: ignore[arg-type]
            NoWaitRateLimiter(),  # type: ignore[arg-type]
        )
    )

    await execute_research_task_async(task_id, "provider-disabled", None, registry)

    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None and task.status is ResearchTaskStatus.FAILED
    assert task.last_error_code == "WEB_SEARCH_PROVIDER_DISABLED"
    assert task.result is not None
    assert task.result["metadata"]["error_code"] == "WEB_SEARCH_PROVIDER_DISABLED"
    assert task.result["metadata"]["provider"] == "disabled"


async def test_empty_web_search_completes_with_zero_results(
    db_session: AsyncSession,
) -> None:
    task_id = await create_task(db_session, ResearchTaskType.WEB_SEARCH)
    registry = ConnectorRegistry()
    registry.register(
        GenericWebSearchConnector(
            FakeWebSearchProvider([]),
            Settings(app_env="test"),
            MemoryCache(),  # type: ignore[arg-type]
            NoWaitRateLimiter(),  # type: ignore[arg-type]
        )
    )

    await execute_research_task_async(task_id, "empty-search", None, registry)

    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None and task.status is ResearchTaskStatus.COMPLETED
    assert task.result is not None
    assert task.result["status"] == "success"
    assert task.result["result_count"] == 0
    assert task.result["metadata"]["search_result_count"] == 0


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


async def test_controlled_search_fetch_persist_and_entity_pipeline(
    db_session: AsyncSession,
) -> None:
    investigation = await InvestigationRepository(db_session).create(
        "Recruiters", "investiga reclutadores de accenture"
    )
    connector, search_client, research_http = controlled_web_connector()
    try:
        output = await connector.execute(
            investigation.original_query,
            ConnectorContext(
                investigation_id=investigation.id,
                task_type=ResearchTaskType.WEB_SEARCH,
            ),
        )
        result = await ResearchArtifactService(db_session).persist(investigation.id, output)
        mentions = await DocumentEntityProcessingService(db_session, get_settings()).process(
            investigation.id, result.document_ids[0]
        )
    finally:
        await search_client.aclose()
        await research_http.client.aclose()

    assert output.metadata["search_result_count"] == 1
    assert output.metadata["source_count"] == 1
    assert output.metadata["fetched_count"] == 1
    assert output.metadata["document_count"] == 1
    assert output.metadata["entity_count"] is None
    assert output.metadata["entity_count_status"] == "downstream"
    assert output.sources[0].title == "Recruiter"
    assert output.sources[0].metadata["status_code"] == 200
    assert output.sources[0].metadata["content_type"] == "text/html"
    assert output.sources[0].metadata["description"] is None
    assert "Public recruiting profile" not in str(output.sources[0].model_dump())
    assert "search_provenance" not in output.sources[0].metadata
    assert output.documents[0].metadata["description"] is None
    assert len(result.source_ids) == len(result.document_ids) == 1
    assert mentions
    assert await db_session.scalar(select(func.count()).select_from(EntityMention)) >= 1
    assert await db_session.scalar(select(func.count()).select_from(Entity)) >= 1


async def test_controlled_web_task_persists_documents_and_enqueues_entities(
    db_session: AsyncSession,
) -> None:
    task_id = await create_task(
        db_session,
        ResearchTaskType.WEB_SEARCH,
        query="investiga reclutadores de accenture",
    )
    connector, search_client, research_http = controlled_web_connector()
    registry = ConnectorRegistry()
    registry.register(connector)
    try:
        await execute_research_task_async(task_id, "controlled-web", None, registry)
    finally:
        await search_client.aclose()
        await research_http.client.aclose()

    db_session.expire_all()
    task = await ResearchTaskRepository(db_session).get_by_id(task_id)
    assert task is not None and task.status is ResearchTaskStatus.COMPLETED
    assert task.result is not None
    assert task.result["status"] == "success"
    assert task.result["metadata"]["source_count"] == 1
    assert task.result["metadata"]["document_count"] == 1
    assert len(task.result["source_ids"]) == len(task.result["document_ids"]) == 1
    events = list(
        await db_session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.task_name == "tracelink.process_document_entities"
            )
        )
    )
    assert len(events) == 1


async def test_web_and_public_mentions_deduplicate_artifacts_and_entity_delivery(
    db_session: AsyncSession,
) -> None:
    investigation = await InvestigationRepository(db_session).create("Dedupe", "ACME")
    connector, search_client, research_http = controlled_web_connector()
    try:
        web = await connector.execute(
            "ACME",
            ConnectorContext(
                investigation_id=investigation.id,
                task_type=ResearchTaskType.WEB_SEARCH,
            ),
        )
        mentions = await connector.execute(
            "ACME",
            ConnectorContext(
                investigation_id=investigation.id,
                task_type=ResearchTaskType.PUBLIC_MENTIONS,
            ),
        )
        first = await ResearchArtifactService(db_session).persist(investigation.id, web)
        second = await ResearchArtifactService(db_session).persist(investigation.id, mentions)
        await enqueue_document_entities_once(db_session, investigation.id, first.document_ids[0])
        await enqueue_document_entities_once(db_session, investigation.id, second.document_ids[0])
    finally:
        await search_client.aclose()
        await research_http.client.aclose()

    assert first.source_ids == second.source_ids
    assert first.document_ids == second.document_ids
    assert await db_session.scalar(select(func.count()).select_from(Source)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 1
    assert await db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    source = await db_session.get(Source, first.source_ids[0])
    assert source is not None
    assert "search_provenance" not in source.metadata_
