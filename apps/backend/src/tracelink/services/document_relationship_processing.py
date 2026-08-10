from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from tracelink.core.config import Settings
from tracelink.domain.enums import (
    AssertionStatus,
    EntityType,
    EvidenceType,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipDecisionType,
    RelationshipType,
)
from tracelink.domain.models import (
    Document,
    Entity,
    EntityMention,
    Relationship,
    RelationshipCandidate,
    Source,
)
from tracelink.domain.normalization import sha256_text
from tracelink.domain.relationship_extraction import (
    MATERIALIZED_RELATIONSHIP_TYPES,
    ExtractedRelationshipCandidate,
    RelationshipExtractionContext,
    RelationshipExtractionProvider,
    ResolvedRelationshipMention,
    canonicalize_relationship_endpoints,
)
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.repositories.investigation_artifacts import InvestigationArtifactRepository
from tracelink.repositories.relationship_candidates import RelationshipCandidateRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.services.deterministic_relationship_extraction import (
    extract_deterministic_relationships,
)
from tracelink.services.document_preprocessing import DocumentChunk, chunk_document
from tracelink.services.errors import DomainNotFoundError
from tracelink.services.relationship_validation import (
    RelationshipValidationService,
    SourceClaim,
    count_independent_sources,
)

logger = logging.getLogger(__name__)


def relationship_candidate_fingerprint(
    investigation_id: UUID,
    document_id: UUID,
    candidate: ExtractedRelationshipCandidate,
) -> str:
    excerpt_locator = (
        f"{candidate.start_offset}:{candidate.end_offset}"
        if candidate.start_offset is not None
        else "no-span"
    )
    identity = (
        f"v1|{investigation_id}|{document_id}|{candidate.source_entity_id}|"
        f"{candidate.target_entity_id}|{candidate.type.value}|{candidate.claim_kind.value}|"
        f"{candidate.temporal_start}|{candidate.temporal_end}|{excerpt_locator}"
    )
    return sha256_text(identity)


def relationship_evidence_fingerprint(
    investigation_id: UUID,
    document_id: UUID,
    relationship_id: UUID,
    evidence_type: EvidenceType,
    start_offset: int | None,
    end_offset: int | None,
    excerpt: str,
) -> str:
    normalized = " ".join(excerpt.split()).casefold()
    return sha256_text(
        f"v1|{investigation_id}|{document_id}|{relationship_id}|{evidence_type.value}|"
        f"{start_offset}|{end_offset}|{normalized}"
    )


def _lock_key(prefix: str, *values: object) -> int:
    digest = hashlib.sha256(f"{prefix}:".encode() + ":".join(map(str, values)).encode()).digest()
    return int.from_bytes(digest[:8], signed=True)


def _candidate_status(decision: RelationshipDecisionType) -> RelationshipCandidateStatus:
    return {
        RelationshipDecisionType.AUTO_ACCEPT: RelationshipCandidateStatus.AUTO_ACCEPTED,
        RelationshipDecisionType.POSSIBLE: RelationshipCandidateStatus.PENDING,
        RelationshipDecisionType.REJECT: RelationshipCandidateStatus.REJECTED,
        RelationshipDecisionType.CONTRADICT: RelationshipCandidateStatus.CONTRADICTED,
    }[decision]


class DocumentRelationshipProcessingService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: RelationshipExtractionProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.candidates = RelationshipCandidateRepository(session)
        self.relationships = RelationshipRepository(session)
        self.evidence = EvidenceRepository(session)
        self.validator = RelationshipValidationService(settings)

    async def _resolved_mentions(
        self, investigation_id: UUID, document_id: UUID
    ) -> list[EntityMention]:
        result = await self.session.scalars(
            select(EntityMention)
            .options(joinedload(EntityMention.entity))
            .where(
                EntityMention.investigation_id == investigation_id,
                EntityMention.document_id == document_id,
                EntityMention.entity_id.is_not(None),
            )
            .order_by(EntityMention.start_offset, EntityMention.id)
        )
        return list(result)

    @staticmethod
    def _chunk_mentions(
        chunk: DocumentChunk, mentions: list[EntityMention]
    ) -> list[ResolvedRelationshipMention]:
        prepared: list[ResolvedRelationshipMention] = []
        for mention in mentions:
            if mention.entity is None or mention.entity_id is None:
                continue
            start, end = mention.start_offset, mention.end_offset
            if start is None or end is None or start < chunk.start_offset or end > chunk.end_offset:
                continue
            prepared.append(
                ResolvedRelationshipMention(
                    mention_id=mention.id,
                    entity_id=mention.entity_id,
                    entity_type=mention.entity_type,
                    canonical_name=mention.entity.canonical_name,
                    surface_form=mention.surface_form,
                    start_offset=start - chunk.start_offset,
                    end_offset=end - chunk.start_offset,
                    confidence=mention.confidence,
                )
            )
        return prepared

    @staticmethod
    def _to_document_candidate(
        candidate: ExtractedRelationshipCandidate,
        chunk: DocumentChunk,
        mentions_by_id: dict[UUID, ResolvedRelationshipMention],
    ) -> ExtractedRelationshipCandidate:
        source_mention = mentions_by_id.get(candidate.source_mention_id)
        target_mention = mentions_by_id.get(candidate.target_mention_id)
        if source_mention is None or target_mention is None:
            raise ValueError("relationship provider referenced an unknown mention")
        if (
            source_mention.entity_id != candidate.source_entity_id
            or target_mention.entity_id != candidate.target_entity_id
        ):
            raise ValueError("relationship provider entity and mention identifiers disagree")
        updates: dict[str, Any] = {}
        if candidate.start_offset is not None and candidate.end_offset is not None:
            start, end = chunk.to_document_offsets(candidate.start_offset, candidate.end_offset)
            updates.update(start_offset=start, end_offset=end)
        source_id, target_id = canonicalize_relationship_endpoints(
            candidate.source_entity_id, candidate.target_entity_id, candidate.type
        )
        if source_id != candidate.source_entity_id:
            updates.update(
                source_entity_id=source_id,
                target_entity_id=target_id,
                source_mention_id=candidate.target_mention_id,
                target_mention_id=candidate.source_mention_id,
            )
        return candidate.model_copy(update=updates)

    async def _shared_address_candidates(
        self, investigation_id: UUID, document: Document, current: list[EntityMention]
    ) -> list[ExtractedRelationshipCandidate]:
        current_addresses = [
            mention
            for mention in current
            if mention.entity_id is not None and mention.entity_type is EntityType.ADDRESS
        ]
        current_organizations = [
            mention
            for mention in current
            if mention.entity_id is not None
            and mention.entity_type in {EntityType.COMPANY, EntityType.ORGANIZATION}
        ]
        if not current_addresses or not current_organizations:
            return []
        all_mentions = list(
            await self.session.scalars(
                select(EntityMention)
                .options(joinedload(EntityMention.entity))
                .where(
                    EntityMention.investigation_id == investigation_id,
                    EntityMention.entity_id.is_not(None),
                )
            )
        )
        output: list[ExtractedRelationshipCandidate] = []
        for address in current_addresses:
            associated: list[EntityMention] = []
            for mention in all_mentions:
                if mention.entity_type not in {EntityType.COMPANY, EntityType.ORGANIZATION}:
                    continue
                matching_addresses = [
                    other
                    for other in all_mentions
                    if other.document_id == mention.document_id
                    and other.entity_id == address.entity_id
                    and other.entity_type is EntityType.ADDRESS
                ]
                if any(
                    item.start_offset is not None
                    and item.end_offset is not None
                    and mention.start_offset is not None
                    and mention.end_offset is not None
                    and max(item.end_offset, mention.end_offset)
                    - min(item.start_offset, mention.start_offset)
                    <= 250
                    for item in matching_addresses
                ):
                    associated.append(mention)
            for left in current_organizations:
                for right in associated:
                    if (
                        left.entity_id == right.entity_id
                        or left.entity_id is None
                        or right.entity_id is None
                    ):
                        continue
                    positions = [
                        value
                        for value in (
                            left.start_offset,
                            left.end_offset,
                            address.start_offset,
                            address.end_offset,
                        )
                        if value is not None
                    ]
                    if len(positions) < 4 or max(positions) - min(positions) > 250:
                        continue
                    output.append(
                        ExtractedRelationshipCandidate(
                            source_mention_id=left.id,
                            target_mention_id=right.id,
                            source_entity_id=left.entity_id,
                            target_entity_id=right.entity_id,
                            type=RelationshipType.SHARES_ADDRESS_WITH,
                            confidence=0.98,
                            start_offset=min(positions),
                            end_offset=max(positions),
                            attributes={
                                "shared_address_entity_id": str(address.entity_id),
                                "corroborating_document_id": str(right.document_id),
                            },
                        )
                    )
        return output

    async def _extract(
        self, investigation_id: UUID, document: Document, mentions: list[EntityMention]
    ) -> list[tuple[str, ExtractedRelationshipCandidate]]:
        chunks = chunk_document(
            document.raw_text,
            chunk_size=self.settings.entity_extraction_chunk_size,
            overlap=self.settings.entity_extraction_chunk_overlap,
        )
        extracted: list[tuple[str, ExtractedRelationshipCandidate]] = []
        for chunk in chunks:
            chunk_mentions = self._chunk_mentions(chunk, mentions)
            if len({mention.entity_id for mention in chunk_mentions}) < 2:
                continue
            by_id = {mention.mention_id: mention for mention in chunk_mentions}
            deterministic = extract_deterministic_relationships(chunk.text, chunk_mentions)
            for item in deterministic:
                method = (
                    "deterministic_rdap"
                    if item.type is RelationshipType.OWNS_DOMAIN
                    else "deterministic_text"
                )
                extracted.append((method, self._to_document_candidate(item, chunk, by_id)))
            if self.provider is not None:
                provider_items = await self.provider.extract(
                    chunk.text,
                    chunk_mentions,
                    MATERIALIZED_RELATIONSHIP_TYPES,
                    RelationshipExtractionContext(
                        investigation_id=investigation_id,
                        document_id=document.id,
                        chunk_index=chunk.index,
                    ),
                )
                for item in provider_items:
                    if item.type is RelationshipType.MENTIONED_IN:
                        continue
                    extracted.append(
                        (self.provider.name, self._to_document_candidate(item, chunk, by_id))
                    )
        for item in await self._shared_address_candidates(investigation_id, document, mentions):
            source_id, target_id = canonicalize_relationship_endpoints(
                item.source_entity_id, item.target_entity_id, item.type
            )
            updates: dict[str, Any] = {}
            if source_id != item.source_entity_id:
                updates = {
                    "source_entity_id": source_id,
                    "target_entity_id": target_id,
                    "source_mention_id": item.target_mention_id,
                    "target_mention_id": item.source_mention_id,
                }
            extracted.append(("deterministic_shared_address", item.model_copy(update=updates)))
        unique: dict[str, tuple[str, ExtractedRelationshipCandidate]] = {}
        for method, item in extracted:
            fingerprint = relationship_candidate_fingerprint(investigation_id, document.id, item)
            previous = unique.get(fingerprint)
            if previous is None or item.confidence > previous[1].confidence:
                unique[fingerprint] = (method, item)
        ordered = sorted(
            unique.values(),
            key=lambda pair: (-pair[1].confidence, pair[0], str(pair[1].source_entity_id)),
        )
        return ordered[: self.settings.relationship_max_candidates_per_document]

    async def _independent_sources(
        self, document: Document, prior_claims: list[RelationshipCandidate]
    ) -> int:
        document_ids = {document.id, *(claim.document_id for claim in prior_claims)}
        rows = await self.session.execute(
            select(Document, Source)
            .join(Source, Source.id == Document.source_id)
            .where(Document.id.in_(document_ids))
        )
        claims = [
            SourceClaim(source.id, item.content_hash, source.publisher, source.url)
            for item, source in rows
        ]
        return count_independent_sources(claims)

    async def _persist_evidence(
        self,
        investigation_id: UUID,
        relationship: Relationship,
        candidate: RelationshipCandidate,
        evidence_type: EvidenceType,
    ) -> None:
        document = await self.session.get(Document, candidate.document_id)
        if document is None:
            raise DomainNotFoundError("candidate document not found")
        excerpt = (
            document.raw_text[candidate.start_offset : candidate.end_offset]
            if candidate.start_offset is not None and candidate.end_offset is not None
            else candidate.supporting_text or ""
        )
        fingerprint = relationship_evidence_fingerprint(
            investigation_id,
            document.id,
            relationship.id,
            evidence_type,
            candidate.start_offset,
            candidate.end_offset,
            excerpt,
        )
        await self.evidence.upsert(
            investigation_id=investigation_id,
            source_id=document.source_id,
            document_id=document.id,
            relationship_id=relationship.id,
            confidence=candidate.score,
            start_offset=candidate.start_offset,
            end_offset=candidate.end_offset,
            locator=f"document:{document.id}",
            excerpt=excerpt,
            evidence_type=evidence_type,
            metadata={
                "relationship_candidate_id": str(candidate.id),
                "claim_kind": candidate.claim_kind.value,
                "extraction_method": candidate.extraction_method,
            },
            fingerprint=fingerprint,
        )

    async def _refresh_observation_times(self, relationship: Relationship) -> None:
        from tracelink.domain.models import Evidence

        first, last = (
            await self.session.execute(
                select(func.min(Evidence.created_at), func.max(Evidence.created_at)).where(
                    Evidence.relationship_id == relationship.id
                )
            )
        ).one()
        relationship.first_observed_at = first
        relationship.last_observed_at = last

    async def process(
        self, investigation_id: UUID, document_id: UUID
    ) -> list[RelationshipCandidate]:
        if not await InvestigationArtifactRepository(self.session).has_document(
            investigation_id, document_id
        ):
            raise DomainNotFoundError("document is not associated with investigation")
        document = await self.session.get(Document, document_id)
        if document is None:
            raise DomainNotFoundError("document not found")
        source = await self.session.get(Source, document.source_id)
        if source is None:
            raise DomainNotFoundError("document source not found")
        await self.session.execute(
            select(
                func.pg_advisory_xact_lock(
                    _lock_key("relationship-document", investigation_id, document_id)
                )
            )
        )
        mentions = await self._resolved_mentions(investigation_id, document_id)
        if len({mention.entity_id for mention in mentions if mention.entity_id is not None}) < 2:
            return []
        extracted = await self._extract(investigation_id, document, mentions)
        entities = {
            entity.id: entity
            for entity in await self.session.scalars(
                select(Entity).where(
                    Entity.id.in_(
                        {
                            entity_id
                            for _, item in extracted
                            for entity_id in (item.source_entity_id, item.target_entity_id)
                        }
                    )
                )
            )
        }
        mentions_by_id = {mention.id: mention for mention in mentions}
        stored: list[RelationshipCandidate] = []
        for method, item in extracted:
            source_entity = entities.get(item.source_entity_id)
            target_entity = entities.get(item.target_entity_id)
            if source_entity is None or target_entity is None:
                continue
            prior_claims = await self.candidates.list_claims(
                investigation_id, item.source_entity_id, item.target_entity_id, item.type
            )
            source_mention = mentions_by_id.get(item.source_mention_id)
            target_mention = mentions_by_id.get(item.target_mention_id)
            endpoint_confidence = min(
                source_mention.confidence if source_mention is not None else item.confidence,
                target_mention.confidence if target_mention is not None else item.confidence,
            )
            quality_value = source.metadata_.get("quality_score")
            source_quality = (
                float(quality_value)
                if isinstance(quality_value, int | float) and 0 <= quality_value <= 1
                else 0.5
            )
            independent_count = await self._independent_sources(document, prior_claims)
            exact_evidence = (
                item.start_offset is not None
                and item.end_offset is not None
                and item.end_offset <= len(document.raw_text)
            )
            decision = self.validator.decide(
                item,
                source_type=source_entity.type,
                target_type=target_entity.type,
                extraction_method=method,
                exact_evidence=exact_evidence,
                endpoint_resolution_confidence=endpoint_confidence,
                source_quality=source_quality,
                independent_source_count=independent_count,
                prior_claims=prior_claims,
            )
            fingerprint = relationship_candidate_fingerprint(investigation_id, document.id, item)
            supporting_text = (
                document.raw_text[item.start_offset : item.end_offset][:1000]
                if exact_evidence and item.start_offset is not None and item.end_offset is not None
                else None
            )
            candidate = await self.candidates.upsert(
                investigation_id=investigation_id,
                document_id=document.id,
                source_entity_id=item.source_entity_id,
                target_entity_id=item.target_entity_id,
                relationship_type=item.type,
                claim_kind=item.claim_kind,
                confidence=item.confidence,
                score=decision.score,
                extraction_method=method,
                supporting_text=supporting_text,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                temporal_start=item.temporal_start,
                temporal_end=item.temporal_end,
                metadata={**dict(item.attributes), "current_state": item.current_state},
                signals={**decision.signals, "reason_codes": decision.reason_codes},
                status=_candidate_status(decision.decision),
                fingerprint=fingerprint,
            )
            stored.append(candidate)
            relationship: Relationship | None = None
            if decision.decision in {
                RelationshipDecisionType.AUTO_ACCEPT,
                RelationshipDecisionType.CONTRADICT,
            }:
                await self.session.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            _lock_key(
                                "relationship-identity",
                                item.source_entity_id,
                                item.target_entity_id,
                                item.type.value,
                            )
                        )
                    )
                )
                relationship = await self.relationships.upsert(
                    source_entity_id=item.source_entity_id,
                    target_entity_id=item.target_entity_id,
                    relationship_type=item.type,
                    confidence=decision.score,
                    status=(
                        AssertionStatus.CONTRADICTED
                        if decision.decision is RelationshipDecisionType.CONTRADICT
                        else AssertionStatus.CONFIRMED
                    ),
                    observed_at=datetime.now(UTC),
                    temporal_start=item.temporal_start,
                    temporal_end=item.temporal_end,
                    metadata={"reason_codes": decision.reason_codes},
                )
                evidence_type = (
                    EvidenceType.CONTRADICTING
                    if item.claim_kind is RelationshipClaimKind.NEGATES
                    else EvidenceType.TEMPORAL_UPDATE
                    if item.claim_kind is RelationshipClaimKind.ENDS
                    else EvidenceType.SUPPORTING
                )
                await self._persist_evidence(
                    investigation_id, relationship, candidate, evidence_type
                )
                if decision.decision is RelationshipDecisionType.CONTRADICT:
                    for prior in prior_claims:
                        if self.validator._contradicts(item, prior):
                            prior.status = RelationshipCandidateStatus.CONTRADICTED
                            prior_type = (
                                EvidenceType.CONTRADICTING
                                if prior.claim_kind is RelationshipClaimKind.NEGATES
                                else EvidenceType.SUPPORTING
                            )
                            await self._persist_evidence(
                                investigation_id, relationship, prior, prior_type
                            )
                await self._refresh_observation_times(relationship)
            logger.info(
                "relationship candidate processed",
                extra={
                    "investigation_id": str(investigation_id),
                    "document_id": str(document_id),
                    "relationship_candidate_id": str(candidate.id),
                    "relationship_id": str(relationship.id) if relationship else None,
                    "relationship_type": item.type.value,
                    "source_entity_id": str(item.source_entity_id),
                    "target_entity_id": str(item.target_entity_id),
                    "decision": decision.decision.value,
                    "score": decision.score,
                    "extraction_method": method,
                },
            )
        await self.session.flush()
        return stored
