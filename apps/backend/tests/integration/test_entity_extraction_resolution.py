from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.connectors.models import ConnectorOutput, DocumentArtifact, SourceArtifact
from tracelink.core.config import get_settings
from tracelink.domain.entity_extraction import (
    EntityExtractionProviderError,
    ExtractedEntityCandidate,
)
from tracelink.domain.enums import (
    EntityResolutionCandidateStatus,
    EntityType,
    InvestigationStatus,
)
from tracelink.domain.models import (
    Entity,
    EntityAlias,
    EntityMention,
    EntityResolutionCandidate,
    InvestigationArtifact,
)
from tracelink.infrastructure.database import get_session, get_session_factory
from tracelink.main import app
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.services.document_entity_processing import DocumentEntityProcessingService
from tracelink.services.entities import EntityService
from tracelink.services.entity_extraction_providers import FakeEntityExtractionProvider
from tracelink.services.research_artifacts import ResearchArtifactService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def add_document(
    session: AsyncSession,
    text: str,
    *,
    investigation_id: UUID | None = None,
    url_suffix: str = "one",
) -> tuple[UUID, UUID]:
    if investigation_id is None:
        investigation = await InvestigationRepository(session).create("Entities", "query")
        investigation_id = investigation.id
    url = f"https://example.com/{url_suffix}"
    output = ConnectorOutput(
        connector="fixture",
        sources=[
            SourceArtifact(
                source_type="web_page",
                url=url,
                normalized_url=url,
                retrieved_at=datetime.now(UTC),
            )
        ],
        documents=[
            DocumentArtifact(
                source_normalized_url=url,
                mime_type="text/plain",
                raw_text=text,
            )
        ],
        result_count=1,
    )
    result = await ResearchArtifactService(session).persist(investigation_id, output)
    return investigation_id, result.document_ids[0]


def fake_person(
    text: str, *, company: str | None = None, role: str | None = None
) -> FakeEntityExtractionProvider:
    attributes = {
        key: value for key, value in {"company": company, "role": role}.items() if value is not None
    }
    return FakeEntityExtractionProvider(
        {
            text: [
                ExtractedEntityCandidate(
                    type=EntityType.PERSON,
                    surface_form="Juan Pérez",
                    canonical_name_candidate="Juan Pérez",
                    confidence=0.95,
                    start_offset=0,
                    end_offset=len("Juan Pérez"),
                    attributes=attributes,
                )
            ]
        }
    )


async def test_document_provenance_mentions_resolution_and_idempotency(
    db_session: AsyncSession,
) -> None:
    investigation_id, document_id = await add_document(
        db_session, "ACME S.A. publica novedades en example.com"
    )
    service = DocumentEntityProcessingService(db_session, get_settings())
    first = await service.process(investigation_id, document_id)
    second = await service.process(investigation_id, document_id)
    assert {mention.entity_type for mention in first} >= {EntityType.COMPANY, EntityType.DOMAIN}
    assert [mention.id for mention in first] == [mention.id for mention in second]
    assert all(mention.entity_id is not None for mention in first)
    assert await db_session.scalar(select(func.count()).select_from(InvestigationArtifact)) == 1
    assert await db_session.scalar(select(func.count()).select_from(EntityMention)) == len(first)


async def test_second_company_mention_matches_and_persists_auto_match(
    db_session: AsyncSession,
) -> None:
    investigation_id, first_document = await add_document(db_session, "ACME S.A.", url_suffix="a")
    _, second_document = await add_document(
        db_session,
        "ACME Sociedad Anónima",
        investigation_id=investigation_id,
        url_suffix="b",
    )
    service = DocumentEntityProcessingService(db_session, get_settings())
    first = await service.process(investigation_id, first_document)
    second = await service.process(investigation_id, second_document)
    company_one = next(item for item in first if item.entity_type is EntityType.COMPANY)
    company_two = next(item for item in second if item.entity_type is EntityType.COMPANY)
    assert company_one.entity_id == company_two.entity_id
    candidate = await db_session.scalar(
        select(EntityResolutionCandidate).where(
            EntityResolutionCandidate.mention_id == company_two.id
        )
    )
    assert candidate is not None
    assert candidate.status is EntityResolutionCandidateStatus.AUTO_MATCHED


async def test_exact_alias_resolves_and_duplicate_alias_is_not_added(
    db_session: AsyncSession,
) -> None:
    entity = await EntityService(EntityRepository(db_session)).create(
        entity_type=EntityType.COMPANY,
        canonical_name="Acme Holdings",
        aliases=["AH"],
    )
    investigation_id, seed_document_id = await add_document(
        db_session, "Acme Holdings", url_suffix="alias-seed"
    )
    db_session.add(
        EntityMention(
            investigation_id=investigation_id,
            document_id=seed_document_id,
            entity_id=entity.id,
            entity_type=EntityType.COMPANY,
            surface_form="Acme Holdings",
            normalized_form="acme holdings",
            start_offset=0,
            end_offset=13,
            extraction_method="fixture",
            confidence=1.0,
            fingerprint="a" * 64,
        )
    )
    await db_session.flush()
    text = "AH"
    _, document_id = await add_document(
        db_session, text, investigation_id=investigation_id, url_suffix="alias-target"
    )
    provider = FakeEntityExtractionProvider(
        {
            text: [
                ExtractedEntityCandidate(
                    type=EntityType.COMPANY,
                    surface_form="AH",
                    canonical_name_candidate="AH",
                    confidence=0.95,
                    start_offset=0,
                    end_offset=2,
                )
            ]
        }
    )
    mention = (
        await DocumentEntityProcessingService(db_session, get_settings(), provider).process(
            investigation_id, document_id
        )
    )[0]
    assert mention.entity_id == entity.id
    assert await db_session.scalar(select(func.count()).select_from(EntityAlias)) == 1


async def test_person_same_name_without_context_creates_possible_separate_entity(
    db_session: AsyncSession,
) -> None:
    text = "Juan Pérez"
    investigation_id, first_document = await add_document(db_session, text, url_suffix="p1")
    _, second_document = await add_document(
        db_session, text + " ", investigation_id=investigation_id, url_suffix="p2"
    )
    provider = fake_person(text)
    first = await DocumentEntityProcessingService(db_session, get_settings(), provider).process(
        investigation_id, first_document
    )
    provider_two = fake_person(text + " ")
    second = await DocumentEntityProcessingService(
        db_session, get_settings(), provider_two
    ).process(investigation_id, second_document)
    assert first[0].entity_id != second[0].entity_id
    candidate = await db_session.scalar(
        select(EntityResolutionCandidate).where(
            EntityResolutionCandidate.mention_id == second[0].id
        )
    )
    assert candidate is not None
    assert candidate.status is EntityResolutionCandidateStatus.PENDING


async def test_person_same_name_and_strong_context_auto_matches(
    db_session: AsyncSession,
) -> None:
    text = "Juan Pérez"
    investigation_id, first_document = await add_document(db_session, text, url_suffix="s1")
    _, second_document = await add_document(
        db_session, text + " ", investigation_id=investigation_id, url_suffix="s2"
    )
    first = await DocumentEntityProcessingService(
        db_session, get_settings(), fake_person(text, company="ACME", role="Director")
    ).process(investigation_id, first_document)
    second = await DocumentEntityProcessingService(
        db_session, get_settings(), fake_person(text + " ", company="acme", role="director")
    ).process(investigation_id, second_document)
    assert first[0].entity_id == second[0].entity_id


async def test_low_confidence_and_type_conflicts_remain_unresolved(
    db_session: AsyncSession,
) -> None:
    text = "Delta"
    investigation_id, document_id = await add_document(db_session, text)
    provider = FakeEntityExtractionProvider(
        {
            text: [
                ExtractedEntityCandidate(
                    type=entity_type,
                    surface_form=text,
                    canonical_name_candidate=(
                        "delta.example" if entity_type is EntityType.DOMAIN else text
                    ),
                    confidence=confidence,
                    start_offset=0,
                    end_offset=len(text),
                )
                for entity_type, confidence in (
                    (EntityType.COMPANY, 0.95),
                    (EntityType.ORGANIZATION, 0.95),
                    (EntityType.PERSON, 0.20),
                )
            ]
        }
    )
    mentions = await DocumentEntityProcessingService(db_session, get_settings(), provider).process(
        investigation_id, document_id
    )
    assert len(mentions) == 3
    assert all(mention.entity_id is None for mention in mentions)


async def test_concurrent_workers_do_not_duplicate_same_document(
    db_session: AsyncSession,
) -> None:
    investigation_id, document_id = await add_document(db_session, "ACME S.A.")
    await db_session.commit()

    async def process() -> None:
        async with get_session_factory()() as session, session.begin():
            await DocumentEntityProcessingService(session, get_settings()).process(
                investigation_id, document_id
            )

    await asyncio.gather(process(), process())
    assert await db_session.scalar(select(func.count()).select_from(EntityMention)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Entity)) == 1


async def test_fake_provider_failure_does_not_change_investigation_or_persist_garbage(
    db_session: AsyncSession,
) -> None:
    text = "provider failure"
    investigation_id, document_id = await add_document(db_session, text)
    provider = FakeEntityExtractionProvider(fail_for=frozenset({text}))
    with pytest.raises(EntityExtractionProviderError):
        await DocumentEntityProcessingService(db_session, get_settings(), provider).process(
            investigation_id, document_id
        )
    investigation = await InvestigationRepository(db_session).get_by_id(investigation_id)
    assert investigation is not None
    assert investigation.status is InvestigationStatus.DRAFT
    assert await db_session.scalar(select(func.count()).select_from(EntityMention)) == 0


async def test_entity_inspection_endpoints(db_session: AsyncSession) -> None:
    investigation_id, document_id = await add_document(db_session, "ACME S.A.")
    mentions = await DocumentEntityProcessingService(db_session, get_settings()).process(
        investigation_id, document_id
    )
    await db_session.commit()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            entities = await client.get(f"/api/investigations/{investigation_id}/entities")
            entity_mentions = await client.get(
                f"/api/investigations/{investigation_id}/entity-mentions"
            )
            candidates = await client.get(
                f"/api/investigations/{investigation_id}/resolution-candidates"
            )
            entity = await client.get(f"/api/entities/{mentions[0].entity_id}")
        assert entities.status_code == 200 and len(entities.json()) == 1
        assert entity_mentions.status_code == 200 and len(entity_mentions.json()) == 1
        assert candidates.status_code == 200 and candidates.json() == []
        assert entity.status_code == 200
    finally:
        app.dependency_overrides.clear()
