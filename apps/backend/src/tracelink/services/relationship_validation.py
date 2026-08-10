from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from tracelink.core.config import Settings
from tracelink.domain.enums import (
    EntityType,
    RelationshipClaimKind,
    RelationshipDecisionType,
)
from tracelink.domain.models import RelationshipCandidate
from tracelink.domain.relationship_extraction import (
    ExtractedRelationshipCandidate,
    relationship_types_compatible,
    temporal_ranges_overlap,
)


class RelationshipDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: RelationshipDecisionType
    score: float = Field(ge=0, le=1)
    reason_codes: list[str]
    signals: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class SourceClaim:
    source_id: UUID
    content_hash: str
    publisher: str | None
    url: str


def count_independent_sources(claims: list[SourceClaim]) -> int:
    accepted_sources: set[UUID] = set()
    accepted_hashes: set[str] = set()
    accepted_publishers: set[str] = set()
    count = 0
    for claim in claims:
        publisher = (claim.publisher or urlsplit(claim.url).hostname or "").casefold()
        if claim.source_id in accepted_sources or claim.content_hash in accepted_hashes:
            continue
        if publisher and publisher in accepted_publishers:
            continue
        accepted_sources.add(claim.source_id)
        accepted_hashes.add(claim.content_hash)
        if publisher:
            accepted_publishers.add(publisher)
        count += 1
    return count


class RelationshipValidationService:
    METHOD_STRENGTH = {
        "deterministic_text": 0.95,
        "deterministic_rdap": 1.0,
        "deterministic_shared_address": 0.95,
        "fake": 0.50,
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _contradicts(
        candidate: ExtractedRelationshipCandidate,
        prior: RelationshipCandidate,
    ) -> bool:
        if (
            candidate.claim_kind is RelationshipClaimKind.ENDS
            or prior.claim_kind is RelationshipClaimKind.ENDS
        ):
            return False
        if candidate.claim_kind is prior.claim_kind:
            return False
        explicit_overlap = temporal_ranges_overlap(
            candidate.temporal_start,
            candidate.temporal_end,
            prior.temporal_start,
            prior.temporal_end,
        )
        prior_current = bool(prior.metadata_.get("current_state", False))
        return explicit_overlap or (candidate.current_state and prior_current)

    def decide(
        self,
        candidate: ExtractedRelationshipCandidate,
        *,
        source_type: EntityType,
        target_type: EntityType,
        extraction_method: str,
        exact_evidence: bool,
        endpoint_resolution_confidence: float,
        source_quality: float,
        independent_source_count: int,
        prior_claims: list[RelationshipCandidate],
    ) -> RelationshipDecision:
        compatible = relationship_types_compatible(candidate.type, source_type, target_type)
        self_reference = candidate.source_entity_id == candidate.target_entity_id
        evidence_valid = candidate.start_offset is not None and candidate.end_offset is not None
        method_strength = self.METHOD_STRENGTH.get(extraction_method, 0.50)
        temporal_agreement = 0.50
        contradictory = any(self._contradicts(candidate, prior) for prior in prior_claims)
        if contradictory:
            temporal_agreement = 0.0
        elif candidate.temporal_start or candidate.temporal_end:
            temporal_agreement = 1.0
        corroboration_bonus = min(max(independent_source_count - 1, 0) * 0.05, 0.10)
        score = min(
            1.0,
            max(
                0.0,
                0.40 * candidate.confidence
                + 0.25 * method_strength
                + 0.15 * float(exact_evidence)
                + 0.10 * endpoint_resolution_confidence
                + 0.05 * source_quality
                + 0.05 * temporal_agreement
                + corroboration_bonus,
            ),
        )
        reason_codes: list[str] = []
        if self_reference:
            reason_codes.append("SELF_REFERENCE")
        if not compatible:
            reason_codes.append("INCOMPATIBLE_ENTITY_TYPES")
        if not evidence_valid:
            reason_codes.append("MISSING_EXACT_EVIDENCE")
        if contradictory:
            reason_codes.append("OVERLAPPING_OPPOSITE_CLAIM")

        if self_reference or not compatible or not evidence_valid:
            decision = RelationshipDecisionType.REJECT
        elif contradictory:
            decision = RelationshipDecisionType.CONTRADICT
        elif candidate.claim_kind is RelationshipClaimKind.NEGATES:
            decision = RelationshipDecisionType.POSSIBLE
            reason_codes.append("UNOPPOSED_NEGATIVE_CLAIM")
        elif candidate.claim_kind is RelationshipClaimKind.ENDS and not prior_claims:
            decision = RelationshipDecisionType.POSSIBLE
            reason_codes.append("TEMPORAL_END_WITHOUT_PRIOR_RELATIONSHIP")
        elif score >= self.settings.relationship_auto_accept_threshold:
            decision = RelationshipDecisionType.AUTO_ACCEPT
            reason_codes.append("AUTO_ACCEPT_THRESHOLD_MET")
        elif score >= self.settings.relationship_possible_threshold:
            decision = RelationshipDecisionType.POSSIBLE
            reason_codes.append("POSSIBLE_THRESHOLD_MET")
        else:
            decision = RelationshipDecisionType.REJECT
            reason_codes.append("BELOW_POSSIBLE_THRESHOLD")
        signals: dict[str, JsonValue] = {
            "compatible_types": compatible,
            "self_reference": self_reference,
            "exact_evidence": exact_evidence,
            "method_strength": round(method_strength, 4),
            "endpoint_resolution_confidence": round(endpoint_resolution_confidence, 4),
            "source_quality": round(source_quality, 4),
            "temporal_agreement": round(temporal_agreement, 4),
            "independent_source_count": independent_source_count,
            "corroboration_bonus": round(corroboration_bonus, 4),
            "claim_kind": candidate.claim_kind.value,
        }
        return RelationshipDecision(
            decision=decision,
            score=round(score, 6),
            reason_codes=reason_codes,
            signals=signals,
        )
