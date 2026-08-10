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
from tracelink.core.config import Settings, get_settings
from tracelink.domain.enums import (
    AssertionStatus,
    EntityType,
    EvidenceType,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipType,
)
from tracelink.domain.models import Evidence, Relationship, RelationshipCandidate
from tracelink.domain.normalization import normalize_entity_name, sha256_text
from tracelink.domain.relationship_extraction import ExtractedRelationshipCandidate
from tracelink.infrastructure.database import get_session, get_session_factory
from tracelink.main import app
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.entity_mentions import EntityMentionRepository
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.services.document_entity_processing import DocumentEntityProcessingService
from tracelink.services.document_relationship_processing import (
    DocumentRelationshipProcessingService,
)
from tracelink.services.entities import EntityService
from tracelink.services.relationship_extraction_providers import (
    FakeRelationshipExtractionProvider,
)
from tracelink.services.research_artifacts import ResearchArtifactService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def add_document(
    session: AsyncSession,
    text: str,
    *,
    investigation_id: UUID | None = None,
    suffix: str = "one",
    mime_type: str = "text/plain",
) -> tuple[UUID, UUID]:
    if investigation_id is None:
        investigation = await InvestigationRepository(session).create("Relationships", "query")
        investigation_id = investigation.id
    url = f"https://{suffix}.example/report"
    result = await ResearchArtifactService(session).persist(
        investigation_id,
        ConnectorOutput(
            connector="fixture",
            sources=[
                SourceArtifact(
                    source_type="fixture",
                    url=url,
                    normalized_url=url,
                    publisher=f"{suffix}.example",
                    retrieved_at=datetime.now(UTC),
                    metadata={"quality_score": 1.0},
                )
            ],
            documents=[
                DocumentArtifact(
                    source_normalized_url=url,
                    mime_type=mime_type,
                    raw_text=text,
                )
            ],
            result_count=1,
        ),
    )
    return investigation_id, result.document_ids[0]


async def add_resolved_mention(
    session: AsyncSession,
    investigation_id: UUID,
    document_id: UUID,
    entity_type: EntityType,
    name: str,
    start: int,
    *,
    entity_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    if entity_id is None:
        entity = await EntityService(EntityRepository(session)).create(
            entity_type=entity_type, canonical_name=name
        )
        entity_id = entity.id
    normalized = normalize_entity_name(entity_type, name)
    mention = await EntityMentionRepository(session).create(
        investigation_id=investigation_id,
        document_id=document_id,
        entity_type=entity_type,
        surface_form=name,
        normalized_form=normalized.comparison_key,
        start_offset=start,
        end_offset=start + len(name),
        chunk_index=0,
        extraction_method="fixture",
        confidence=0.98,
        fingerprint=sha256_text(f"{document_id}:{entity_id}:{start}:{name}"),
        metadata={},
    )
    mention.entity_id = entity_id
    await session.flush()
    return mention.id, entity_id


async def test_strong_text_creates_relationship_evidence_idempotently_and_api_reads_it(
    db_session: AsyncSession,
) -> None:
    text = "Dr. Juan Pérez fue designado director de ACME S.A."
    investigation_id, document_id = await add_document(db_session, text)
    await DocumentEntityProcessingService(db_session, get_settings()).process(
        investigation_id, document_id
    )
    service = DocumentRelationshipProcessingService(db_session, get_settings())
    first = await service.process(investigation_id, document_id)
    second = await service.process(investigation_id, document_id)
    await db_session.commit()

    assert len(first) == 1
    assert [item.id for item in first] == [item.id for item in second]
    relationship = await db_session.scalar(select(Relationship))
    evidence = await db_session.scalar(select(Evidence))
    assert relationship is not None and relationship.type is RelationshipType.DIRECTOR_OF
    assert relationship.status is AssertionStatus.CONFIRMED
    assert evidence is not None and evidence.relationship_id == relationship.id
    assert evidence.excerpt is None
    assert await db_session.scalar(select(func.count()).select_from(RelationshipCandidate)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Relationship)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Evidence)) == 1

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            relationships = await client.get(
                f"/api/investigations/{investigation_id}/relationships"
            )
            candidates = await client.get(
                f"/api/investigations/{investigation_id}/relationship-candidates"
            )
            detail = await client.get(f"/api/relationships/{relationship.id}")
            evidence_response = await client.get(f"/api/relationships/{relationship.id}/evidence")
        assert relationships.status_code == 200 and relationships.json()[0]["evidence_count"] == 1
        assert candidates.status_code == 200 and candidates.json()[0]["status"] == "AUTO_ACCEPTED"
        assert detail.status_code == 200 and detail.json()["source_entity"]["type"] == "PERSON"
        assert evidence_response.status_code == 200
        assert "designado director" in evidence_response.json()[0]["preview"]
    finally:
        app.dependency_overrides.clear()


async def test_possible_self_incompatible_and_symmetric_candidates(
    db_session: AsyncSession,
) -> None:
    text = "Alpha Beta"
    investigation_id, document_id = await add_document(db_session, text)
    alpha_mention, alpha = await add_resolved_mention(
        db_session, investigation_id, document_id, EntityType.COMPANY, "Alpha", 0
    )
    beta_mention, beta = await add_resolved_mention(
        db_session, investigation_id, document_id, EntityType.COMPANY, "Beta", 6
    )
    responses = {
        text: [
            ExtractedRelationshipCandidate(
                source_mention_id=alpha_mention,
                target_mention_id=beta_mention,
                source_entity_id=alpha,
                target_entity_id=beta,
                type=RelationshipType.PARTNER_OF,
                confidence=0.99,
                start_offset=0,
                end_offset=len(text),
            ),
            ExtractedRelationshipCandidate(
                source_mention_id=beta_mention,
                target_mention_id=alpha_mention,
                source_entity_id=beta,
                target_entity_id=alpha,
                type=RelationshipType.PARTNER_OF,
                confidence=0.99,
                start_offset=0,
                end_offset=len(text),
            ),
            ExtractedRelationshipCandidate(
                source_mention_id=alpha_mention,
                target_mention_id=alpha_mention,
                source_entity_id=alpha,
                target_entity_id=alpha,
                type=RelationshipType.RELATED_TO,
                confidence=1.0,
                start_offset=0,
                end_offset=5,
            ),
            ExtractedRelationshipCandidate(
                source_mention_id=alpha_mention,
                target_mention_id=beta_mention,
                source_entity_id=alpha,
                target_entity_id=beta,
                type=RelationshipType.DIRECTOR_OF,
                confidence=1.0,
                start_offset=0,
                end_offset=len(text),
            ),
        ]
    }
    settings = Settings(relationship_auto_accept_threshold=0.80)
    items = await DocumentRelationshipProcessingService(
        db_session, settings, FakeRelationshipExtractionProvider(responses)
    ).process(investigation_id, document_id)
    assert len(items) == 3
    assert sum(item.status is RelationshipCandidateStatus.AUTO_ACCEPTED for item in items) == 1
    assert sum(item.status is RelationshipCandidateStatus.REJECTED for item in items) == 2
    relationship = await db_session.scalar(select(Relationship))
    assert relationship is not None and relationship.type is RelationshipType.PARTNER_OF
    assert relationship.source_entity_id < relationship.target_entity_id

    possible_text = "Gamma Delta"
    _, possible_document = await add_document(
        db_session, possible_text, investigation_id=investigation_id, suffix="possible"
    )
    gamma_mention, gamma = await add_resolved_mention(
        db_session, investigation_id, possible_document, EntityType.COMPANY, "Gamma", 0
    )
    delta_mention, delta = await add_resolved_mention(
        db_session, investigation_id, possible_document, EntityType.COMPANY, "Delta", 6
    )
    provider = FakeRelationshipExtractionProvider(
        {
            possible_text: [
                ExtractedRelationshipCandidate(
                    source_mention_id=gamma_mention,
                    target_mention_id=delta_mention,
                    source_entity_id=gamma,
                    target_entity_id=delta,
                    type=RelationshipType.PARTNER_OF,
                    confidence=0.70,
                    start_offset=0,
                    end_offset=len(possible_text),
                )
            ]
        }
    )
    possible = await DocumentRelationshipProcessingService(
        db_session, get_settings(), provider
    ).process(investigation_id, possible_document)
    assert possible[0].status is RelationshipCandidateStatus.PENDING


async def test_two_documents_add_evidence_and_temporal_conflict_is_preserved(
    db_session: AsyncSession,
) -> None:
    investigation_id, first_document = await add_document(db_session, "Juan ACME", suffix="first")
    _, second_document = await add_document(
        db_session, "Juan no ACME", investigation_id=investigation_id, suffix="second"
    )
    first_person_mention, person = await add_resolved_mention(
        db_session, investigation_id, first_document, EntityType.PERSON, "Juan", 0
    )
    first_company_mention, company = await add_resolved_mention(
        db_session, investigation_id, first_document, EntityType.COMPANY, "ACME", 5
    )
    second_person_mention, _ = await add_resolved_mention(
        db_session,
        investigation_id,
        second_document,
        EntityType.PERSON,
        "Juan",
        0,
        entity_id=person,
    )
    second_company_mention, _ = await add_resolved_mention(
        db_session,
        investigation_id,
        second_document,
        EntityType.COMPANY,
        "ACME",
        8,
        entity_id=company,
    )
    affirm = ExtractedRelationshipCandidate(
        source_mention_id=first_person_mention,
        target_mention_id=first_company_mention,
        source_entity_id=person,
        target_entity_id=company,
        type=RelationshipType.DIRECTOR_OF,
        confidence=0.99,
        start_offset=0,
        end_offset=9,
        temporal_start="2023",
        temporal_end="2023",
    )
    negate = ExtractedRelationshipCandidate(
        source_mention_id=second_person_mention,
        target_mention_id=second_company_mention,
        source_entity_id=person,
        target_entity_id=company,
        type=RelationshipType.DIRECTOR_OF,
        claim_kind=RelationshipClaimKind.NEGATES,
        confidence=0.99,
        start_offset=0,
        end_offset=12,
        temporal_start="2023",
        temporal_end="2023",
    )
    settings = Settings(relationship_auto_accept_threshold=0.80)
    await DocumentRelationshipProcessingService(
        db_session,
        settings,
        FakeRelationshipExtractionProvider({"Juan ACME": [affirm]}),
    ).process(investigation_id, first_document)
    result = await DocumentRelationshipProcessingService(
        db_session,
        settings,
        FakeRelationshipExtractionProvider({"Juan no ACME": [negate]}),
    ).process(investigation_id, second_document)
    relationship = await db_session.scalar(select(Relationship))
    assert result[0].status is RelationshipCandidateStatus.CONTRADICTED
    assert relationship is not None and relationship.status is AssertionStatus.CONTRADICTED
    evidence_types = set(await db_session.scalars(select(Evidence.evidence_type)))
    assert evidence_types == {EvidenceType.SUPPORTING, EvidenceType.CONTRADICTING}


async def test_two_supporting_documents_deduplicate_and_nonoverlap_is_not_contradiction(
    db_session: AsyncSession,
) -> None:
    investigation_id, first_document = await add_document(db_session, "Juan ACME", suffix="time-a")
    _, second_document = await add_document(
        db_session, "Juan ACME again", investigation_id=investigation_id, suffix="time-b"
    )
    _, negative_document = await add_document(
        db_session, "Juan not ACME", investigation_id=investigation_id, suffix="time-c"
    )
    person_id: UUID | None = None
    company_id: UUID | None = None
    prepared: list[tuple[str, UUID, UUID, UUID, UUID]] = []
    for text, document_id, company_start in (
        ("Juan ACME", first_document, 5),
        ("Juan ACME again", second_document, 5),
        ("Juan not ACME", negative_document, 9),
    ):
        person_mention, person_id = await add_resolved_mention(
            db_session,
            investigation_id,
            document_id,
            EntityType.PERSON,
            "Juan",
            0,
            entity_id=person_id,
        )
        company_mention, company_id = await add_resolved_mention(
            db_session,
            investigation_id,
            document_id,
            EntityType.COMPANY,
            "ACME",
            company_start,
            entity_id=company_id,
        )
        prepared.append((text, document_id, person_mention, company_mention, person_id))
    assert person_id is not None and company_id is not None
    settings = Settings(relationship_auto_accept_threshold=0.80)
    for text, document_id, person_mention, company_mention, _ in prepared[:2]:
        affirm = ExtractedRelationshipCandidate(
            source_mention_id=person_mention,
            target_mention_id=company_mention,
            source_entity_id=person_id,
            target_entity_id=company_id,
            type=RelationshipType.DIRECTOR_OF,
            confidence=0.99,
            start_offset=0,
            end_offset=len(text),
            temporal_start="2022",
            temporal_end="2022",
        )
        await DocumentRelationshipProcessingService(
            db_session, settings, FakeRelationshipExtractionProvider({text: [affirm]})
        ).process(investigation_id, document_id)
    negative_text, negative_doc, person_mention, company_mention, _ = prepared[2]
    negative = ExtractedRelationshipCandidate(
        source_mention_id=person_mention,
        target_mention_id=company_mention,
        source_entity_id=person_id,
        target_entity_id=company_id,
        type=RelationshipType.DIRECTOR_OF,
        claim_kind=RelationshipClaimKind.NEGATES,
        confidence=0.99,
        start_offset=0,
        end_offset=len(negative_text),
        temporal_start="2023",
        temporal_end="2023",
    )
    negative_result = await DocumentRelationshipProcessingService(
        db_session,
        settings,
        FakeRelationshipExtractionProvider({negative_text: [negative]}),
    ).process(investigation_id, negative_doc)
    relationship = await db_session.scalar(select(Relationship))
    assert relationship is not None and relationship.status is AssertionStatus.CONFIRMED
    assert negative_result[0].status is RelationshipCandidateStatus.PENDING
    assert await db_session.scalar(select(func.count()).select_from(Relationship)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Evidence)) == 2


async def test_shared_address_and_concurrent_reprocessing_converge(
    db_session: AsyncSession,
) -> None:
    investigation_id, first_document = await add_document(
        db_session, "Alpha Calle Central 123", suffix="address-one"
    )
    _, second_document = await add_document(
        db_session,
        "Beta Calle Central 123",
        investigation_id=investigation_id,
        suffix="address-two",
    )
    _, alpha = await add_resolved_mention(
        db_session, investigation_id, first_document, EntityType.COMPANY, "Alpha", 0
    )
    _, address = await add_resolved_mention(
        db_session, investigation_id, first_document, EntityType.ADDRESS, "Calle Central 123", 6
    )
    await add_resolved_mention(
        db_session, investigation_id, second_document, EntityType.COMPANY, "Beta", 0
    )
    await add_resolved_mention(
        db_session,
        investigation_id,
        second_document,
        EntityType.ADDRESS,
        "Calle Central 123",
        5,
        entity_id=address,
    )
    await db_session.commit()

    async def process() -> None:
        async with get_session_factory()() as session, session.begin():
            await DocumentRelationshipProcessingService(session, get_settings()).process(
                investigation_id, second_document
            )

    await asyncio.gather(process(), process())
    await db_session.rollback()
    relationship = await db_session.scalar(
        select(Relationship).where(Relationship.type == RelationshipType.SHARES_ADDRESS_WITH)
    )
    assert relationship is not None
    assert alpha in {relationship.source_entity_id, relationship.target_entity_id}
    assert await db_session.scalar(select(func.count()).select_from(Relationship)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Evidence)) == 1


async def test_provider_failure_rolls_back_without_garbage(db_session: AsyncSession) -> None:
    text = "Alpha Beta"
    investigation_id, document_id = await add_document(db_session, text)
    await add_resolved_mention(
        db_session, investigation_id, document_id, EntityType.COMPANY, "Alpha", 0
    )
    await add_resolved_mention(
        db_session, investigation_id, document_id, EntityType.COMPANY, "Beta", 6
    )
    provider = FakeRelationshipExtractionProvider(fail_for=frozenset({text}))
    with pytest.raises(RuntimeError, match="fake relationship extraction failed"):
        await DocumentRelationshipProcessingService(db_session, get_settings(), provider).process(
            investigation_id, document_id
        )
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(RelationshipCandidate)) == 0
