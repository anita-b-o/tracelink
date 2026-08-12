from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracelink.domain.enums import (
    AssertionStatus,
    EntityResolutionCandidateStatus,
    EvidenceType,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
)
from tracelink.domain.models import (
    Entity,
    EntityAlias,
    EntityMention,
    EntityResolutionCandidate,
    Evidence,
    Relationship,
    RelationshipCandidate,
)
from tracelink.domain.relationship_extraction import (
    canonicalize_relationship_endpoints,
    relationship_types_compatible,
)
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.repositories.investigation_artifacts import InvestigationArtifactRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.services.document_relationship_processing import relationship_evidence_fingerprint
from tracelink.services.errors import DomainConflictError, DomainNotFoundError


class EntityCandidateReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _candidate(self, candidate_id: UUID) -> EntityResolutionCandidate:
        candidate = await self.session.scalar(
            select(EntityResolutionCandidate)
            .options(
                selectinload(EntityResolutionCandidate.mention)
                .selectinload(EntityMention.entity)
                .selectinload(Entity.aliases),
                selectinload(EntityResolutionCandidate.candidate_entity).selectinload(
                    Entity.aliases
                ),
            )
            .where(EntityResolutionCandidate.id == candidate_id)
            .with_for_update()
        )
        if candidate is None:
            raise DomainNotFoundError("entity resolution candidate not found")
        return candidate

    @staticmethod
    def _require_pending(
        candidate: EntityResolutionCandidate, target: EntityResolutionCandidateStatus
    ) -> bool:
        if candidate.status is target:
            return False
        if candidate.status is not EntityResolutionCandidateStatus.PENDING:
            raise DomainConflictError(
                f"entity resolution candidate is already {candidate.status.value}"
            )
        return True

    async def reject(self, candidate_id: UUID) -> EntityResolutionCandidate:
        candidate = await self._candidate(candidate_id)
        if self._require_pending(candidate, EntityResolutionCandidateStatus.REJECTED):
            candidate.status = EntityResolutionCandidateStatus.REJECTED
            candidate.reviewed_at = datetime.now(UTC)
            await self.session.flush()
        return candidate

    async def accept(self, candidate_id: UUID) -> EntityResolutionCandidate:
        candidate = await self._candidate(candidate_id)
        if not self._require_pending(candidate, EntityResolutionCandidateStatus.ACCEPTED):
            return candidate
        mention = candidate.mention
        provisional = mention.entity
        target = candidate.candidate_entity
        if provisional is None:
            raise DomainConflictError("candidate mention no longer has a provisional entity")
        if provisional.id == target.id:
            raise DomainConflictError("candidate already points to the resolved entity")
        if provisional.type is not target.type or mention.entity_type is not target.type:
            raise DomainConflictError("candidate entity type is incompatible with the mention")
        if provisional.metadata_.get("resolution_provisional") is not True:
            raise DomainConflictError("candidate source entity is not provisional")

        await self.session.execute(
            select(Entity.id)
            .where(Entity.id.in_([provisional.id, target.id]))
            .order_by(Entity.id)
            .with_for_update()
        )
        existing_keys = {target.comparison_key, *(alias.comparison_key for alias in target.aliases)}
        alias_values = [
            (provisional.canonical_name, provisional.normalized_name, provisional.comparison_key),
            *[
                (alias.alias, alias.normalized_alias, alias.comparison_key)
                for alias in provisional.aliases
            ],
        ]
        for alias, normalized, comparison_key in alias_values:
            if comparison_key in existing_keys:
                continue
            self.session.add(
                EntityAlias(
                    entity_id=target.id,
                    alias=alias,
                    normalized_alias=normalized,
                    comparison_key=comparison_key,
                )
            )
            existing_keys.add(comparison_key)

        await self.session.execute(
            update(EntityMention)
            .where(
                EntityMention.entity_id == provisional.id,
                EntityMention.investigation_id == candidate.investigation_id,
            )
            .values(entity_id=target.id)
        )
        dependent_candidates = list(
            await self.session.scalars(
                select(RelationshipCandidate)
                .where(
                    RelationshipCandidate.investigation_id == candidate.investigation_id,
                    or_(
                        RelationshipCandidate.source_entity_id == provisional.id,
                        RelationshipCandidate.target_entity_id == provisional.id,
                    ),
                )
                .with_for_update()
            )
        )
        now = datetime.now(UTC)
        for dependent in dependent_candidates:
            source_id = (
                target.id
                if dependent.source_entity_id == provisional.id
                else dependent.source_entity_id
            )
            target_id = (
                target.id
                if dependent.target_entity_id == provisional.id
                else dependent.target_entity_id
            )
            source_id, target_id = canonicalize_relationship_endpoints(
                source_id, target_id, dependent.type
            )
            source_entity = (
                target if source_id == target.id else await self.session.get(Entity, source_id)
            )
            target_entity = (
                target if target_id == target.id else await self.session.get(Entity, target_id)
            )
            if (
                source_id == target_id
                or source_entity is None
                or target_entity is None
                or not relationship_types_compatible(
                    dependent.type, source_entity.type, target_entity.type
                )
            ):
                dependent.status = RelationshipCandidateStatus.REJECTED
                dependent.reviewed_at = now
                dependent.signals = {
                    **dependent.signals,
                    "reason_codes": ["ENTITY_MERGE_INVALIDATED"],
                }
                continue
            dependent.source_entity_id = source_id
            dependent.target_entity_id = target_id

        relationship_ids = select(Evidence.relationship_id).where(
            Evidence.investigation_id == candidate.investigation_id,
            Evidence.relationship_id.is_not(None),
        )
        relationships = list(
            await self.session.scalars(
                select(Relationship)
                .where(
                    Relationship.id.in_(relationship_ids),
                    or_(
                        Relationship.source_entity_id == provisional.id,
                        Relationship.target_entity_id == provisional.id,
                    ),
                )
                .with_for_update()
            )
        )
        repository = RelationshipRepository(self.session)
        for relationship in relationships:
            source_id = (
                target.id
                if relationship.source_entity_id == provisional.id
                else relationship.source_entity_id
            )
            target_id = (
                target.id
                if relationship.target_entity_id == provisional.id
                else relationship.target_entity_id
            )
            source_id, target_id = canonicalize_relationship_endpoints(
                source_id, target_id, relationship.type
            )
            if source_id == target_id:
                await self.session.execute(
                    update(Evidence)
                    .where(
                        Evidence.relationship_id == relationship.id,
                        Evidence.investigation_id == candidate.investigation_id,
                    )
                    .values(relationship_id=None, entity_id=target.id)
                )
                continue
            if (
                source_id != relationship.source_entity_id
                or target_id != relationship.target_entity_id
            ):
                existing = await repository.upsert(
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relationship_type=relationship.type,
                    confidence=relationship.confidence,
                    status=relationship.status,
                    observed_at=now,
                    temporal_start=relationship.temporal_start,
                    temporal_end=relationship.temporal_end,
                    metadata={"entity_resolution_candidate_id": str(candidate.id)},
                )
                await self.session.execute(
                    update(Evidence)
                    .where(
                        Evidence.relationship_id == relationship.id,
                        Evidence.investigation_id == candidate.investigation_id,
                    )
                    .values(relationship_id=existing.id)
                )

        provisional.metadata_ = {
            **provisional.metadata_,
            "resolution_provisional": False,
            "resolution_merged_into": str(target.id),
            "resolution_merged_at": now.isoformat(),
        }
        candidate.status = EntityResolutionCandidateStatus.ACCEPTED
        candidate.reviewed_at = now
        await self.session.execute(
            update(EntityResolutionCandidate)
            .where(
                EntityResolutionCandidate.mention_id == mention.id,
                EntityResolutionCandidate.id != candidate.id,
                EntityResolutionCandidate.status == EntityResolutionCandidateStatus.PENDING,
            )
            .values(status=EntityResolutionCandidateStatus.REJECTED, reviewed_at=now)
        )
        await self.session.flush()
        return candidate


class RelationshipCandidateReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _candidate(self, candidate_id: UUID) -> RelationshipCandidate:
        candidate = await self.session.scalar(
            select(RelationshipCandidate)
            .options(
                selectinload(RelationshipCandidate.source_entity),
                selectinload(RelationshipCandidate.target_entity),
                selectinload(RelationshipCandidate.document),
            )
            .where(RelationshipCandidate.id == candidate_id)
            .with_for_update()
        )
        if candidate is None:
            raise DomainNotFoundError("relationship candidate not found")
        return candidate

    @staticmethod
    def _require_pending(
        candidate: RelationshipCandidate, target: RelationshipCandidateStatus
    ) -> bool:
        if candidate.status is target:
            return False
        if candidate.status is not RelationshipCandidateStatus.PENDING:
            raise DomainConflictError(f"relationship candidate is already {candidate.status.value}")
        return True

    async def reject(self, candidate_id: UUID) -> RelationshipCandidate:
        candidate = await self._candidate(candidate_id)
        if self._require_pending(candidate, RelationshipCandidateStatus.REJECTED):
            candidate.status = RelationshipCandidateStatus.REJECTED
            candidate.reviewed_at = datetime.now(UTC)
            await self.session.flush()
        return candidate

    async def accept(self, candidate_id: UUID) -> RelationshipCandidate:
        candidate = await self._candidate(candidate_id)
        if not self._require_pending(candidate, RelationshipCandidateStatus.ACCEPTED):
            return candidate
        source_id, target_id = canonicalize_relationship_endpoints(
            candidate.source_entity_id, candidate.target_entity_id, candidate.type
        )
        if source_id == target_id:
            raise DomainConflictError("self-referential relationship candidate cannot be accepted")
        if not relationship_types_compatible(
            candidate.type, candidate.source_entity.type, candidate.target_entity.type
        ):
            raise DomainConflictError("relationship candidate entity types are incompatible")
        document = candidate.document
        if (
            candidate.start_offset is None
            or candidate.end_offset is None
            or candidate.start_offset < 0
            or candidate.end_offset <= candidate.start_offset
            or candidate.end_offset > len(document.raw_text)
        ):
            raise DomainConflictError("relationship candidate lacks valid exact evidence")
        if not await InvestigationArtifactRepository(self.session).has_document(
            candidate.investigation_id, document.id
        ):
            raise DomainConflictError("candidate document is not part of the investigation")
        if candidate.claim_kind is RelationshipClaimKind.ENDS and not (
            candidate.temporal_end or candidate.temporal_start
        ):
            raise DomainConflictError("ENDS candidate requires a temporal value")

        now = datetime.now(UTC)
        status = (
            AssertionStatus.CONTRADICTED
            if candidate.claim_kind is RelationshipClaimKind.NEGATES
            else AssertionStatus.CONFIRMED
        )
        temporal_end = (
            candidate.temporal_end or candidate.temporal_start
            if candidate.claim_kind is RelationshipClaimKind.ENDS
            else candidate.temporal_end
        )
        relationship = await RelationshipRepository(self.session).upsert(
            source_entity_id=source_id,
            target_entity_id=target_id,
            relationship_type=candidate.type,
            confidence=candidate.score,
            status=status,
            observed_at=now,
            temporal_start=candidate.temporal_start,
            temporal_end=temporal_end,
            metadata={"human_review_candidate_id": str(candidate.id)},
        )
        evidence_type = (
            EvidenceType.CONTRADICTING
            if candidate.claim_kind is RelationshipClaimKind.NEGATES
            else EvidenceType.TEMPORAL_UPDATE
            if candidate.claim_kind is RelationshipClaimKind.ENDS
            else EvidenceType.SUPPORTING
        )
        excerpt = document.raw_text[candidate.start_offset : candidate.end_offset]
        fingerprint = relationship_evidence_fingerprint(
            candidate.investigation_id,
            document.id,
            relationship.id,
            evidence_type,
            candidate.start_offset,
            candidate.end_offset,
            excerpt,
        )
        await EvidenceRepository(self.session).upsert(
            investigation_id=candidate.investigation_id,
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
                "human_reviewed": True,
            },
            fingerprint=fingerprint,
        )
        candidate.source_entity_id = source_id
        candidate.target_entity_id = target_id
        candidate.status = RelationshipCandidateStatus.ACCEPTED
        candidate.reviewed_at = now
        await self.session.flush()
        return candidate
