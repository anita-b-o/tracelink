from datetime import date
from uuid import UUID, uuid4

import pytest

from tracelink.core.config import Settings
from tracelink.domain.enums import (
    EntityType,
    EvidenceType,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipDecisionType,
    RelationshipType,
)
from tracelink.domain.models import RelationshipCandidate
from tracelink.domain.relationship_extraction import (
    RELATIONSHIP_TYPE_COMPATIBILITY,
    ExtractedRelationshipCandidate,
    RelationshipExtractionContext,
    RelationshipProviderOutputError,
    ResolvedRelationshipMention,
    canonicalize_relationship_endpoints,
    partial_date_bounds,
    relationship_types_compatible,
    temporal_ranges_overlap,
    validate_partial_date,
)
from tracelink.services.deterministic_relationship_extraction import (
    extract_deterministic_relationships,
)
from tracelink.services.document_relationship_processing import (
    relationship_candidate_fingerprint,
    relationship_evidence_fingerprint,
)
from tracelink.services.relationship_extraction_providers import (
    FakeRelationshipExtractionProvider,
)
from tracelink.services.relationship_validation import (
    RelationshipValidationService,
    SourceClaim,
    count_independent_sources,
)


def mention(
    entity_type: EntityType, name: str, start: int, *, entity_id: UUID | None = None
) -> ResolvedRelationshipMention:
    return ResolvedRelationshipMention(
        mention_id=uuid4(),
        entity_id=entity_id or uuid4(),
        entity_type=entity_type,
        canonical_name=name,
        surface_form=name,
        start_offset=start,
        end_offset=start + len(name),
        confidence=0.95,
    )


def candidate(
    source: ResolvedRelationshipMention,
    target: ResolvedRelationshipMention,
    relationship_type: RelationshipType,
    *,
    confidence: float = 0.95,
    claim_kind: RelationshipClaimKind = RelationshipClaimKind.AFFIRMS,
    temporal_start: str | None = None,
    temporal_end: str | None = None,
    current_state: bool = False,
) -> ExtractedRelationshipCandidate:
    return ExtractedRelationshipCandidate(
        source_mention_id=source.mention_id,
        target_mention_id=target.mention_id,
        source_entity_id=source.entity_id,
        target_entity_id=target.entity_id,
        type=relationship_type,
        claim_kind=claim_kind,
        confidence=confidence,
        start_offset=0,
        end_offset=20,
        temporal_start=temporal_start,
        temporal_end=temporal_end,
        current_state=current_state,
    )


@pytest.mark.parametrize(
    ("relationship_type", "source_type", "target_type", "expected"),
    [
        (RelationshipType.DIRECTOR_OF, EntityType.PERSON, EntityType.COMPANY, True),
        (RelationshipType.DIRECTOR_OF, EntityType.COMPANY, EntityType.PERSON, False),
        (RelationshipType.OWNER_OF, EntityType.COMPANY, EntityType.DOMAIN, True),
        (RelationshipType.EMPLOYEE_OF, EntityType.PERSON, EntityType.ORGANIZATION, True),
        (RelationshipType.OWNS_DOMAIN, EntityType.ORGANIZATION, EntityType.DOMAIN, True),
        (RelationshipType.SUBSIDIARY_OF, EntityType.COMPANY, EntityType.COMPANY, True),
        (RelationshipType.PARTNER_OF, EntityType.PERSON, EntityType.COMPANY, True),
        (RelationshipType.SHARES_ADDRESS_WITH, EntityType.COMPANY, EntityType.PERSON, False),
        (RelationshipType.RELATED_TO, EntityType.ADDRESS, EntityType.DOCUMENT, True),
    ],
)
def test_relationship_compatibility_matrix(
    relationship_type: RelationshipType,
    source_type: EntityType,
    target_type: EntityType,
    expected: bool,
) -> None:
    assert relationship_types_compatible(relationship_type, source_type, target_type) is expected
    assert set(RELATIONSHIP_TYPE_COMPATIBILITY) == set(RelationshipType)


def test_symmetric_canonicalization_but_directed_order_is_preserved() -> None:
    low, high = UUID(int=1), UUID(int=2)
    assert canonicalize_relationship_endpoints(high, low, RelationshipType.RELATED_TO) == (
        low,
        high,
    )
    assert canonicalize_relationship_endpoints(high, low, RelationshipType.DIRECTOR_OF) == (
        high,
        low,
    )


def test_partial_temporal_values_preserve_precision_and_overlap() -> None:
    assert partial_date_bounds("2023") == (date(2023, 1, 1), date(2023, 12, 31))
    assert partial_date_bounds("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    assert temporal_ranges_overlap("2023", "2023", "2023-06", "2024")
    assert not temporal_ranges_overlap("2022", "2022", "2023", "2023")
    with pytest.raises(ValueError):
        validate_partial_date("2023-02-30")


def test_textual_director_owner_employee_and_temporal_end() -> None:
    text = (
        "Juan Pérez fue designado director de ACME S.A. en 2020. "
        "Juan Pérez trabaja para ACME S.A. "
        "ACME S.A. pertenece a Juan Pérez. "
        "Juan Pérez dejó de ser director de ACME S.A. en 2023."
    )
    person = mention(EntityType.PERSON, "Juan Pérez", 0)
    company = mention(EntityType.COMPANY, "ACME S.A.", 38)
    extracted = extract_deterministic_relationships(text, [person, company])
    assert {item.type for item in extracted} >= {
        RelationshipType.DIRECTOR_OF,
        RelationshipType.EMPLOYEE_OF,
        RelationshipType.OWNER_OF,
    }
    ended = next(item for item in extracted if item.claim_kind is RelationshipClaimKind.ENDS)
    assert ended.temporal_end == "2023"


def test_rdap_owns_domain_requires_public_registrant_not_registrar() -> None:
    company = mention(EntityType.COMPANY, "Example Inc.", 0)
    domain = mention(EntityType.DOMAIN, "example.com", 0)
    public = (
        '{"ldhName":"example.com","entities":[{"roles":["registrant"],'
        '"vcardArray":["vcard",[["org",{},"text","Example Inc."]]]}]}'
    )
    registrar = public.replace("registrant", "registrar")
    redacted = public.replace("Example Inc.", "REDACTED FOR PRIVACY")
    assert [
        item.type for item in extract_deterministic_relationships(public, [company, domain])
    ] == [RelationshipType.OWNS_DOMAIN]
    assert extract_deterministic_relationships(registrar, [company, domain]) == []
    assert extract_deterministic_relationships(redacted, [company, domain]) == []


def test_scoring_thresholds_self_reference_and_contradiction() -> None:
    settings = Settings()
    service = RelationshipValidationService(settings)
    person = mention(EntityType.PERSON, "Juan Pérez", 0)
    company = mention(EntityType.COMPANY, "ACME S.A.", 10)
    strong = candidate(person, company, RelationshipType.DIRECTOR_OF, current_state=True)
    accepted = service.decide(
        strong,
        source_type=EntityType.PERSON,
        target_type=EntityType.COMPANY,
        extraction_method="deterministic_text",
        exact_evidence=True,
        endpoint_resolution_confidence=0.95,
        source_quality=0.5,
        independent_source_count=1,
        prior_claims=[],
    )
    assert accepted.decision is RelationshipDecisionType.AUTO_ACCEPT

    self_reference = strong.model_copy(
        update={
            "target_entity_id": strong.source_entity_id,
            "target_mention_id": strong.source_mention_id,
        }
    )
    rejected = service.decide(
        self_reference,
        source_type=EntityType.PERSON,
        target_type=EntityType.PERSON,
        extraction_method="fake",
        exact_evidence=True,
        endpoint_resolution_confidence=1.0,
        source_quality=1.0,
        independent_source_count=3,
        prior_claims=[],
    )
    assert rejected.decision is RelationshipDecisionType.REJECT
    assert "SELF_REFERENCE" in rejected.reason_codes

    prior = RelationshipCandidate(
        investigation_id=uuid4(),
        document_id=uuid4(),
        source_entity_id=person.entity_id,
        target_entity_id=company.entity_id,
        type=RelationshipType.DIRECTOR_OF,
        claim_kind=RelationshipClaimKind.AFFIRMS,
        confidence=0.9,
        score=0.9,
        extraction_method="fake",
        start_offset=0,
        end_offset=5,
        temporal_start="2023",
        temporal_end="2023",
        metadata_={},
        signals={},
        status=RelationshipCandidateStatus.PENDING,
        fingerprint="a" * 64,
    )
    negative = candidate(
        person,
        company,
        RelationshipType.DIRECTOR_OF,
        claim_kind=RelationshipClaimKind.NEGATES,
        temporal_start="2023",
        temporal_end="2023",
    )
    contradicted = service.decide(
        negative,
        source_type=EntityType.PERSON,
        target_type=EntityType.COMPANY,
        extraction_method="fake",
        exact_evidence=True,
        endpoint_resolution_confidence=0.95,
        source_quality=0.5,
        independent_source_count=2,
        prior_claims=[prior],
    )
    assert contradicted.decision is RelationshipDecisionType.CONTRADICT


def test_independent_sources_and_fingerprints_are_stable() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    claims = [
        SourceClaim(first, "same", "one.example", "https://one.example/a"),
        SourceClaim(second, "same", "two.example", "https://two.example/copy"),
        SourceClaim(third, "other", "three.example", "https://three.example/report"),
    ]
    assert count_independent_sources(claims) == 2
    person = mention(EntityType.PERSON, "Juan", 0)
    company = mention(EntityType.COMPANY, "ACME", 5)
    item = candidate(person, company, RelationshipType.DIRECTOR_OF)
    investigation_id, document_id, relationship_id = uuid4(), uuid4(), uuid4()
    assert relationship_candidate_fingerprint(investigation_id, document_id, item) == (
        relationship_candidate_fingerprint(investigation_id, document_id, item)
    )
    assert relationship_evidence_fingerprint(
        investigation_id,
        document_id,
        relationship_id,
        evidence_type=EvidenceType.SUPPORTING,
        start_offset=0,
        end_offset=4,
        excerpt="  ACME  ",
    ) == relationship_evidence_fingerprint(
        investigation_id,
        document_id,
        relationship_id,
        evidence_type=EvidenceType.SUPPORTING,
        start_offset=0,
        end_offset=4,
        excerpt="ACME",
    )


@pytest.mark.asyncio
async def test_fake_provider_supports_results_failure_and_invalid_output() -> None:
    person = mention(EntityType.PERSON, "Juan", 0)
    company = mention(EntityType.COMPANY, "ACME", 5)
    item = candidate(person, company, RelationshipType.DIRECTOR_OF)
    context = RelationshipExtractionContext(
        investigation_id=uuid4(), document_id=uuid4(), chunk_index=0
    )
    provider = FakeRelationshipExtractionProvider({"ok": [item]}, invalid_for=frozenset({"bad"}))
    assert await provider.extract(
        "ok", [person, company], frozenset({RelationshipType.DIRECTOR_OF}), context
    ) == [item]
    with pytest.raises(RelationshipProviderOutputError):
        await provider.extract(
            "bad", [person, company], frozenset({RelationshipType.DIRECTOR_OF}), context
        )
