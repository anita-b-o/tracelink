from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import AssertionStatus, EntityType, RelationshipType
from tracelink.domain.models import (
    Document,
    EmbeddingRecord,
    Entity,
    EntityAlias,
    Evidence,
    Finding,
    Investigation,
    Source,
)
from tracelink.repositories.documents import DocumentRepository
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.repositories.findings import FindingRepository
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.repositories.sources import SourceRepository
from tracelink.services.documents import DocumentService
from tracelink.services.entities import EntityService
from tracelink.services.evidence import EvidenceService
from tracelink.services.relationships import RelationshipService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def create_entity(session: AsyncSession, name: str) -> Entity:
    return await EntityService(EntityRepository(session)).create(
        entity_type=EntityType.COMPANY,
        canonical_name=name,
    )


async def test_create_investigation_entity_and_alias_search(db_session: AsyncSession) -> None:
    investigation = await InvestigationRepository(db_session).create(
        "Ownership review", "Who owns ACME?"
    )
    entity = await EntityService(EntityRepository(db_session)).create(
        entity_type=EntityType.COMPANY,
        canonical_name="  ACME   Holdings ",
        aliases=["ACME", "ＡＣＭＥ Argentina"],
    )

    assert investigation.id is not None
    assert entity.normalized_name == "acme holdings"
    assert len(await EntityRepository(db_session).find_by_normalized_name("acme holdings")) == 1
    assert [item.id for item in await EntityRepository(db_session).find_by_alias("acme")] == [
        entity.id
    ]


async def test_duplicate_alias_is_rejected_by_database(db_session: AsyncSession) -> None:
    entity = await create_entity(db_session, "ACME")
    repository = EntityRepository(db_session)
    await repository.add_alias(entity, "ACME Corp", "acme corp")
    with pytest.raises(IntegrityError):
        await repository.add_alias(entity, "acme corp", "acme corp")


async def test_relationship_service_and_database_constraints(db_session: AsyncSession) -> None:
    source = await create_entity(db_session, "Parent Corp")
    target = await create_entity(db_session, "Subsidiary Corp")
    repository = RelationshipRepository(db_session)
    service = RelationshipService(db_session, repository)
    relationship = await service.create(
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type=RelationshipType.OWNER_OF,
        confidence=0.95,
        status=AssertionStatus.CONFIRMED,
    )
    duplicate = await service.create(
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type=RelationshipType.OWNER_OF,
        confidence=0.5,
        status=AssertionStatus.POSSIBLE,
    )

    assert duplicate.id == relationship.id
    with pytest.raises(ValueError, match="same entity"):
        await service.create(
            source_entity_id=source.id,
            target_entity_id=source.id,
            relationship_type=RelationshipType.RELATED_TO,
            confidence=0.5,
            status=AssertionStatus.POSSIBLE,
        )


@pytest.mark.parametrize("self_reference,confidence", [(False, 1.5), (True, 0.5)])
async def test_relationship_constraints_are_enforced_by_database(
    db_session: AsyncSession, self_reference: bool, confidence: float
) -> None:
    source = await create_entity(db_session, "Entity A")
    target = source if self_reference else await create_entity(db_session, "Entity B")
    with pytest.raises(IntegrityError):
        await RelationshipRepository(db_session).create(
            source_entity_id=source.id,
            target_entity_id=target.id,
            relationship_type=RelationshipType.RELATED_TO,
            confidence=confidence,
            status=AssertionStatus.UNVERIFIED,
        )


async def test_evidence_targets_and_document_source_coherence(db_session: AsyncSession) -> None:
    investigation = await InvestigationRepository(db_session).create("Case", "Query")
    entity_a = await create_entity(db_session, "Entity A")
    entity_b = await create_entity(db_session, "Entity B")
    relationship = await RelationshipService(db_session, RelationshipRepository(db_session)).create(
        source_entity_id=entity_a.id,
        target_entity_id=entity_b.id,
        relationship_type=RelationshipType.RELATED_TO,
        confidence=0.7,
        status=AssertionStatus.PROBABLE,
    )
    source = await SourceRepository(db_session).create(
        source_type="WEB", url="https://example.com/report"
    )
    other_source = await SourceRepository(db_session).create(
        source_type="WEB", url="https://example.org/report"
    )
    document = await DocumentService(db_session, DocumentRepository(db_session)).create(
        source_id=source.id, mime_type="text/html", raw_text="Report"
    )
    service = EvidenceService(db_session, EvidenceRepository(db_session))

    entity_evidence = await service.create(
        investigation_id=investigation.id,
        source_id=source.id,
        document_id=document.id,
        entity_id=entity_a.id,
        confidence=0.8,
    )
    relationship_evidence = await service.create(
        investigation_id=investigation.id,
        source_id=source.id,
        relationship_id=relationship.id,
        confidence=0.75,
    )

    assert entity_evidence.entity_id == entity_a.id
    assert relationship_evidence.relationship_id == relationship.id
    with pytest.raises(ValueError, match="entity or a relationship"):
        await service.create(
            investigation_id=investigation.id,
            source_id=source.id,
            confidence=0.5,
        )
    with pytest.raises(ValueError, match="does not belong"):
        await service.create(
            investigation_id=investigation.id,
            source_id=other_source.id,
            document_id=document.id,
            entity_id=entity_a.id,
            confidence=0.5,
        )


async def test_evidence_target_constraint_is_enforced_by_database(
    db_session: AsyncSession,
) -> None:
    investigation = await InvestigationRepository(db_session).create("Case", "Query")
    source = await SourceRepository(db_session).create(source_type="WEB", url="https://example.com")
    with pytest.raises(IntegrityError):
        await EvidenceRepository(db_session).create(
            investigation_id=investigation.id,
            source_id=source.id,
            confidence=0.5,
        )


async def test_document_hash_deduplication_preserves_sources(db_session: AsyncSession) -> None:
    source_repository = SourceRepository(db_session)
    source_a = await source_repository.create(source_type="WEB", url="https://a.example")
    source_b = await source_repository.create(source_type="WEB", url="https://b.example")
    service = DocumentService(db_session, DocumentRepository(db_session))

    first = await service.create(
        source_id=source_a.id, mime_type="text/plain", raw_text="same content"
    )
    duplicate = await service.create(
        source_id=source_a.id, mime_type="text/plain", raw_text="same content"
    )
    other_source_copy = await service.create(
        source_id=source_b.id, mime_type="text/plain", raw_text="same content"
    )

    assert duplicate.id == first.id
    assert other_source_copy.id != first.id
    assert len(await DocumentRepository(db_session).find_by_content_hash(first.content_hash)) == 2
    assert [source.id for source in await source_repository.find_by_url(source_a.url)] == [
        source_a.id
    ]


async def test_document_deletion_cascades_to_derived_embeddings(db_session: AsyncSession) -> None:
    source = await SourceRepository(db_session).create(
        source_type="WEB", url="https://embedding.example"
    )
    document = await DocumentService(db_session, DocumentRepository(db_session)).create(
        source_id=source.id, mime_type="text/plain", raw_text="chunk"
    )
    embedding = EmbeddingRecord(
        document_id=document.id,
        chunk_index=0,
        chunk_text="chunk",
        embedding=[0.1, 0.2, 0.3],
        metadata_={},
    )
    db_session.add(embedding)
    await db_session.flush()

    await db_session.execute(delete(Document).where(Document.id == document.id))
    await db_session.flush()
    assert (
        await db_session.scalar(select(EmbeddingRecord).where(EmbeddingRecord.id == embedding.id))
        is None
    )


async def test_investigation_and_alias_cascades_preserve_shared_records(
    db_session: AsyncSession,
) -> None:
    investigation = await InvestigationRepository(db_session).create("Case", "Query")
    entity = await EntityService(EntityRepository(db_session)).create(
        entity_type=EntityType.COMPANY,
        canonical_name="ACME",
        aliases=["ACME Corp"],
    )
    source = await SourceRepository(db_session).create(source_type="WEB", url="https://example.com")
    await EvidenceService(db_session, EvidenceRepository(db_session)).create(
        investigation_id=investigation.id,
        source_id=source.id,
        entity_id=entity.id,
        confidence=1.0,
    )
    await FindingRepository(db_session).create(
        investigation_id=investigation.id,
        title="Finding",
        description="Description",
        confidence=0.9,
        status=AssertionStatus.CONFIRMED,
    )
    await db_session.execute(delete(Investigation).where(Investigation.id == investigation.id))
    await db_session.flush()

    assert await db_session.scalar(select(Evidence)) is None
    assert await db_session.scalar(select(Finding)) is None
    assert await db_session.get(Entity, entity.id) is not None
    assert await db_session.get(Source, source.id) is not None

    await db_session.execute(delete(Entity).where(Entity.id == entity.id))
    await db_session.flush()
    assert await db_session.scalar(select(EntityAlias)) is None


async def test_referenced_entities_are_restricted_from_deletion(db_session: AsyncSession) -> None:
    source = await create_entity(db_session, "Entity A")
    target = await create_entity(db_session, "Entity B")
    await RelationshipService(db_session, RelationshipRepository(db_session)).create(
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type=RelationshipType.RELATED_TO,
        confidence=0.5,
        status=AssertionStatus.POSSIBLE,
    )

    with pytest.raises(IntegrityError):
        await db_session.execute(delete(Entity).where(Entity.id == source.id))


async def test_enum_constraint_rejects_unknown_value(db_session: AsyncSession) -> None:
    invalid = Entity(
        id=uuid4(),
        type="UNKNOWN",  # type: ignore[arg-type]
        canonical_name="Unknown",
        normalized_name="unknown",
        metadata_={},
    )
    db_session.add(invalid)
    with pytest.raises((LookupError, StatementError)):
        await db_session.flush()
