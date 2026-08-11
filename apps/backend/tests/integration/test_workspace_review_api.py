from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_relationship_extraction_evidence import (
    add_document,
    add_resolved_mention,
)
from tracelink.domain.enums import (
    AssertionStatus,
    EntityResolutionCandidateStatus,
    EntityType,
    EvidenceType,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipType,
)
from tracelink.domain.models import (
    Document,
    EntityMention,
    EntityResolutionCandidate,
    Evidence,
    Relationship,
    RelationshipCandidate,
)
from tracelink.infrastructure.database import get_session
from tracelink.main import app
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.entity_mentions import EntityResolutionCandidateRepository
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.repositories.relationship_candidates import RelationshipCandidateRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.services.entities import EntityService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_workspace_contracts_filters_graph_and_review_are_transactional(
    db_session: AsyncSession,
) -> None:
    text = "Jane Doe directs Acme SA since 2020."
    investigation_id, document_id = await add_document(db_session, text, suffix="workspace")
    entities = EntityService(EntityRepository(db_session))
    target = await entities.create(entity_type=EntityType.COMPANY, canonical_name="ACME")
    provisional = await entities.create(
        entity_type=EntityType.COMPANY,
        canonical_name="Acme SA",
        metadata={"resolution_provisional": True},
    )
    person = await entities.create(entity_type=EntityType.PERSON, canonical_name="Jane Doe")
    company_mention_id, _ = await add_resolved_mention(
        db_session,
        investigation_id,
        document_id,
        EntityType.COMPANY,
        "Acme SA",
        text.index("Acme SA"),
        entity_id=provisional.id,
    )
    await add_resolved_mention(
        db_session,
        investigation_id,
        document_id,
        EntityType.PERSON,
        "Jane Doe",
        0,
        entity_id=person.id,
    )
    await EntityResolutionCandidateRepository(db_session).upsert(
        investigation_id=investigation_id,
        mention_id=company_mention_id,
        candidate_entity_id=target.id,
        score=0.83,
        status=EntityResolutionCandidateStatus.PENDING,
        signals={"name_similarity": 0.9},
    )
    entity_candidate = await db_session.scalar(select(EntityResolutionCandidate))
    assert entity_candidate is not None
    entity_candidate_id = entity_candidate.id
    target_id = target.id
    provisional_id = provisional.id
    person_id = person.id
    await db_session.commit()
    db_session.expire_all()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            summary = await client.get(f"/api/investigations/{investigation_id}")
            assert summary.status_code == 200
            assert summary.json()["counts"] == {
                "tasks": 0,
                "entities": 2,
                "relationships": 0,
                "contradictions": 0,
                "sources": 1,
                "documents": 1,
            }
            filtered = await client.get(
                f"/api/investigations/{investigation_id}/entities",
                params={"type": "COMPANY", "q": "acme", "sort": "mention_count"},
            )
            assert filtered.status_code == 200 and len(filtered.json()) == 1
            assert filtered.json()[0]["mention_count"] == 1
            sources = await client.get(f"/api/investigations/{investigation_id}/sources")
            documents = await client.get(f"/api/investigations/{investigation_id}/documents")
            assert sources.json()[0]["document_count"] == 1
            assert documents.json()[0]["text_preview"].startswith("Jane Doe")
            document = await client.get(f"/api/documents/{document_id}")
            assert document.status_code == 200 and document.json()["content"] == text

            stored_document = await db_session.get(Document, document_id)
            assert stored_document is not None
            source_id = stored_document.source_id
            dependent_candidate = await RelationshipCandidateRepository(db_session).upsert(
                investigation_id=investigation_id,
                document_id=document_id,
                source_entity_id=person_id,
                target_entity_id=provisional_id,
                relationship_type=RelationshipType.DIRECTOR_OF,
                claim_kind=RelationshipClaimKind.AFFIRMS,
                confidence=0.86,
                score=0.84,
                extraction_method="fixture",
                supporting_text=text,
                start_offset=0,
                end_offset=len(text),
                temporal_start="2020",
                temporal_end=None,
                metadata={},
                signals={"reason_codes": ["HUMAN_REVIEW"]},
                status=RelationshipCandidateStatus.PENDING,
                fingerprint="a" * 64,
            )
            dependent_candidate_id = dependent_candidate.id
            dependent_relationship = await RelationshipRepository(db_session).create(
                source_entity_id=person_id,
                target_entity_id=provisional_id,
                relationship_type=RelationshipType.DIRECTOR_OF,
                confidence=0.8,
                status=AssertionStatus.CONFIRMED,
                temporal_start="2020",
                metadata={"before_entity_merge": True},
            )
            dependent_relationship_id = dependent_relationship.id
            preserved_evidence = await EvidenceRepository(db_session).create(
                investigation_id=investigation_id,
                source_id=source_id,
                document_id=document_id,
                relationship_id=dependent_relationship_id,
                excerpt=text,
                start_offset=0,
                end_offset=len(text),
                evidence_type=EvidenceType.SUPPORTING,
                confidence=0.8,
                metadata={"before_entity_merge": True},
            )
            preserved_evidence_id = preserved_evidence.id
            await db_session.commit()

            accepted = await client.post(
                f"/api/entity-resolution-candidates/{entity_candidate_id}/accept"
            )
            assert accepted.status_code == 200 and accepted.json()["status"] == "ACCEPTED"
            assert (
                await db_session.scalar(
                    select(EntityMention.entity_id).where(EntityMention.id == company_mention_id)
                )
                == target_id
            )
            assert (
                await db_session.scalar(
                    select(Relationship.target_entity_id).where(
                        Relationship.id == dependent_relationship_id
                    )
                )
                == target_id
            )
            assert (
                await db_session.scalar(
                    select(RelationshipCandidate.target_entity_id).where(
                        RelationshipCandidate.id == dependent_candidate_id
                    )
                )
                == target_id
            )
            assert (
                await db_session.scalar(
                    select(Evidence.relationship_id).where(Evidence.id == preserved_evidence_id)
                )
                == dependent_relationship_id
            )
            repeated = await client.post(
                f"/api/entity-resolution-candidates/{entity_candidate_id}/accept"
            )
            changed = await client.post(
                f"/api/entity-resolution-candidates/{entity_candidate_id}/reject"
            )
            assert repeated.status_code == 200
            assert changed.status_code == 409

            invalid_candidate = await RelationshipCandidateRepository(db_session).upsert(
                investigation_id=investigation_id,
                document_id=document_id,
                source_entity_id=target_id,
                target_entity_id=person_id,
                relationship_type=RelationshipType.DIRECTOR_OF,
                claim_kind=RelationshipClaimKind.AFFIRMS,
                confidence=0.86,
                score=0.84,
                extraction_method="fixture",
                supporting_text=text,
                start_offset=0,
                end_offset=len(text),
                temporal_start="2020",
                temporal_end=None,
                metadata={},
                signals={"reason_codes": ["INCOMPATIBLE_ENDPOINTS"]},
                status=RelationshipCandidateStatus.PENDING,
                fingerprint="b" * 64,
            )
            invalid_candidate_id = invalid_candidate.id
            await db_session.commit()
            invalid_accept = await client.post(
                f"/api/relationship-candidates/{invalid_candidate_id}/accept"
            )
            assert invalid_accept.status_code == 409
            pending_after_rollback = await client.get(
                f"/api/investigations/{investigation_id}/relationship-candidates",
                params={"status": "PENDING"},
            )
            assert pending_after_rollback.status_code == 200
            assert any(
                row["id"] == str(invalid_candidate_id) and row["status"] == "PENDING"
                for row in pending_after_rollback.json()
            )

            accepted_relationship = await client.post(
                f"/api/relationship-candidates/{dependent_candidate_id}/accept"
            )
            assert accepted_relationship.status_code == 200
            assert accepted_relationship.json()["status"] == "ACCEPTED"
            assert (
                await client.post(f"/api/relationship-candidates/{dependent_candidate_id}/accept")
            ).status_code == 200
            assert (
                await client.post(f"/api/relationship-candidates/{dependent_candidate_id}/reject")
            ).status_code == 409

            rejected_candidate = await RelationshipCandidateRepository(db_session).upsert(
                investigation_id=investigation_id,
                document_id=document_id,
                source_entity_id=person_id,
                target_entity_id=target_id,
                relationship_type=RelationshipType.DIRECTOR_OF,
                claim_kind=RelationshipClaimKind.NEGATES,
                confidence=0.72,
                score=0.7,
                extraction_method="fixture",
                supporting_text=text,
                start_offset=0,
                end_offset=len(text),
                temporal_start="2020",
                temporal_end=None,
                metadata={},
                signals={"reason_codes": ["HUMAN_REVIEW"]},
                status=RelationshipCandidateStatus.PENDING,
                fingerprint="c" * 64,
            )
            rejected_candidate_id = rejected_candidate.id
            await db_session.commit()
            rejected = await client.post(
                f"/api/relationship-candidates/{rejected_candidate_id}/reject"
            )
            assert rejected.status_code == 200
            assert rejected.json()["status"] == "REJECTED"
            assert rejected.json()["reviewed_at"] is not None
            assert (
                await client.post(f"/api/relationship-candidates/{rejected_candidate_id}/reject")
            ).status_code == 200
            assert (
                await client.post(f"/api/relationship-candidates/{rejected_candidate_id}/accept")
            ).status_code == 409

            relationships = await client.get(
                f"/api/investigations/{investigation_id}/relationships",
                params={"type": "DIRECTOR_OF", "entity_id": str(target_id)},
            )
            assert relationships.status_code == 200 and len(relationships.json()) == 1
            relationship_id = relationships.json()[0]["id"]
            detail = await client.get(
                f"/api/investigations/{investigation_id}/relationships/{relationship_id}"
            )
            assert detail.status_code == 200
            preserved = next(
                item
                for item in detail.json()["evidence"]
                if item["id"] == str(preserved_evidence_id)
            )
            assert preserved["relationship_id"] == relationship_id
            assert preserved["document_id"] == str(document_id)
            assert preserved["preview"] == text
            human_reviewed = next(
                item
                for item in detail.json()["evidence"]
                if item["metadata"].get("relationship_candidate_id") == str(dependent_candidate_id)
            )
            assert human_reviewed["investigation_id"] == str(investigation_id)
            assert human_reviewed["source_id"] == str(source_id)
            assert human_reviewed["document_id"] == str(document_id)
            assert human_reviewed["relationship_id"] == relationship_id
            assert human_reviewed["start_offset"] == 0
            assert human_reviewed["end_offset"] == len(text)
            assert human_reviewed["preview"] == text
            assert human_reviewed["metadata"]["human_reviewed"] is True
            assert (await client.get(f"/api/evidence/{human_reviewed['id']}")).status_code == 200
            full_graph = await client.get(f"/api/investigations/{investigation_id}/graph")
            assert len(full_graph.json()["edges"]) == 1
            assert any(
                node["id"] == str(target_id) and node["mention_count"] == 1
                for node in full_graph.json()["nodes"]
            )
            graph = await client.get(
                f"/api/investigations/{investigation_id}/graph", params={"max_nodes": 1}
            )
            assert graph.status_code == 200
            assert graph.json()["truncated"] is True
            assert len(graph.json()["nodes"]) == 1
            assert (
                await client.post(
                    "/api/entity-resolution-candidates/00000000-0000-0000-0000-000000000000/accept"
                )
            ).status_code == 404
    finally:
        app.dependency_overrides.clear()
