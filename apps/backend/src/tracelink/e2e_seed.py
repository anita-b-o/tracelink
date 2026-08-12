"""Idempotent, offline-only workspace fixture used by compose.e2e.yaml."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from tracelink.connectors.models import ConnectorOutput, DocumentArtifact, SourceArtifact
from tracelink.core.config import get_settings
from tracelink.domain.enums import (
    AssertionStatus,
    EntityResolutionCandidateStatus,
    EntityType,
    EvidenceType,
    InvestigationStatus,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipType,
)
from tracelink.domain.models import EntityMention, Investigation, User
from tracelink.domain.normalization import normalize_entity_name, sha256_text
from tracelink.infrastructure.database import close_database, get_session_factory
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.entity_mentions import (
    EntityMentionRepository,
    EntityResolutionCandidateRepository,
)
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.relationship_candidates import RelationshipCandidateRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.services.auth import normalize_email
from tracelink.services.entities import EntityService
from tracelink.services.research_artifacts import ResearchArtifactService

FIXTURE_TITLE = "Review and graph fixture"


async def seed() -> None:
    settings = get_settings()
    if settings.app_env != "test" or not settings.e2e_seed_enabled:
        raise SystemExit("E2E seed requires APP_ENV=test and E2E_SEED_ENABLED=true")
    async with get_session_factory()() as session:
        owner = await session.scalar(
            select(User).where(User.email == normalize_email(settings.dev_bootstrap_email))
        )
        if owner is None:
            raise SystemExit("E2E owner is missing; run the test bootstrap migration first")
        existing = await session.scalar(
            select(Investigation).where(
                Investigation.title == FIXTURE_TITLE, Investigation.user_id == owner.id
            )
        )
        if existing is not None:
            return
        investigation = await InvestigationRepository(session).create(
            FIXTURE_TITLE,
            "Review entity resolution and relationship evidence for ACME",
            user_id=owner.id,
        )
        investigation.status = InvestigationStatus.COMPLETED
        text = "Jane Doe directs Acme SA since 2020. ACME disputes an ownership allegation."
        url = "https://fixtures.tracelink.test/acme-filing"
        persisted = await ResearchArtifactService(session).persist(
            investigation.id,
            ConnectorOutput(
                connector="e2e_fixture",
                sources=[
                    SourceArtifact(
                        source_type="fixture",
                        url=url,
                        normalized_url=url,
                        publisher="TraceLink Fixture Registry",
                        title="ACME registry filing",
                        published_at=datetime(2024, 6, 2, tzinfo=UTC),
                        retrieved_at=datetime.now(UTC),
                        metadata={"offline_fixture": True},
                    )
                ],
                documents=[
                    DocumentArtifact(
                        source_normalized_url=url, mime_type="text/plain", raw_text=text
                    )
                ],
                result_count=1,
            ),
        )
        document_id = persisted.document_ids[0]
        source_id = persisted.source_ids[0]
        entities = EntityService(EntityRepository(session))
        company = await entities.create(entity_type=EntityType.COMPANY, canonical_name="ACME")
        provisional = await entities.create(
            entity_type=EntityType.COMPANY,
            canonical_name="Acme SA",
            metadata={"resolution_provisional": True},
        )
        person = await entities.create(entity_type=EntityType.PERSON, canonical_name="Jane Doe")
        mentions = EntityMentionRepository(session)

        async def mention(
            name: str, entity_type: EntityType, entity_id: UUID, start: int
        ) -> EntityMention:
            normalized = normalize_entity_name(entity_type, name)
            item = await mentions.create(
                investigation_id=investigation.id,
                document_id=document_id,
                entity_type=entity_type,
                surface_form=name,
                normalized_form=normalized.comparison_key,
                start_offset=start,
                end_offset=start + len(name),
                chunk_index=0,
                extraction_method="e2e_fixture",
                confidence=0.96,
                fingerprint=sha256_text(f"{document_id}:{name}:{start}"),
                metadata={},
            )
            item.entity_id = entity_id
            await session.flush()
            return item

        person_mention = await mention("Jane Doe", EntityType.PERSON, person.id, 0)
        company_start = text.index("Acme SA")
        company_mention = await mention(
            "Acme SA", EntityType.COMPANY, provisional.id, company_start
        )
        await EntityResolutionCandidateRepository(session).upsert(
            investigation_id=investigation.id,
            mention_id=company_mention.id,
            candidate_entity_id=company.id,
            score=0.84,
            status=EntityResolutionCandidateStatus.PENDING,
            signals={"name_similarity": 0.91, "reason": "normalized alias"},
        )
        relationship = await RelationshipRepository(session).create(
            source_entity_id=person.id,
            target_entity_id=company.id,
            relationship_type=RelationshipType.DIRECTOR_OF,
            confidence=0.92,
            status=AssertionStatus.CONFIRMED,
            first_observed_at=datetime.now(UTC),
            last_observed_at=datetime.now(UTC),
            temporal_start="2020",
            metadata={"fixture": True},
        )
        await EvidenceRepository(session).create(
            investigation_id=investigation.id,
            source_id=source_id,
            document_id=document_id,
            relationship_id=relationship.id,
            excerpt="Jane Doe directs Acme SA since 2020.",
            start_offset=0,
            end_offset=39,
            evidence_type=EvidenceType.SUPPORTING,
            confidence=0.92,
            metadata={"fixture": True},
        )
        allegation_start = text.index("ACME disputes")
        await RelationshipCandidateRepository(session).upsert(
            investigation_id=investigation.id,
            document_id=document_id,
            source_entity_id=person.id,
            target_entity_id=company.id,
            relationship_type=RelationshipType.OWNER_OF,
            claim_kind=RelationshipClaimKind.NEGATES,
            confidence=0.74,
            score=0.72,
            extraction_method="e2e_fixture",
            supporting_text=text[allegation_start:],
            start_offset=allegation_start,
            end_offset=len(text),
            temporal_start="2024-06",
            temporal_end=None,
            metadata={"fixture": True},
            signals={"reason_codes": ["CONTRADICTORY_LANGUAGE"]},
            status=RelationshipCandidateStatus.PENDING,
            fingerprint=sha256_text(f"{investigation.id}:pending-relationship"),
        )
        _ = person_mention
        await session.commit()


async def main() -> None:
    try:
        await seed()
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
