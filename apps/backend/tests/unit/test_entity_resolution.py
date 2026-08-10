from datetime import UTC, datetime
from uuid import uuid4

from tracelink.domain.enums import EntityType
from tracelink.domain.models import Entity
from tracelink.domain.normalization import normalize_entity_name
from tracelink.services.entity_resolution import (
    EntityResolutionService,
    GeneratedEntityCandidate,
)


def entity(
    entity_type: EntityType,
    name: str,
    *,
    context: dict[str, str] | None = None,
) -> Entity:
    normalized = normalize_entity_name(entity_type, name)
    return Entity(
        id=uuid4(),
        type=entity_type,
        canonical_name=normalized.canonical,
        normalized_name=normalized.normalized,
        comparison_key=normalized.comparison_key,
        metadata_={"resolution_context": context or {}},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_exact_name_and_alias_scores_are_explainable() -> None:
    company = entity(EntityType.COMPANY, "Acme Sociedad Anónima")
    normalized = normalize_entity_name(EntityType.COMPANY, "ACME S.A.")
    exact_score, exact_signals, _ = EntityResolutionService._score(
        GeneratedEntityCandidate(company, 1.0, False), normalized, {}
    )
    alias_score, alias_signals, _ = EntityResolutionService._score(
        GeneratedEntityCandidate(company, 1.0, True), normalized, {}
    )
    assert exact_score == 0.90
    assert exact_signals["exact_normalized_name"] is True
    assert alias_score == 0.93
    assert alias_signals["exact_alias"] is True


def test_person_name_alone_has_no_strong_context() -> None:
    person = entity(EntityType.PERSON, "Juan Pérez")
    score, signals, strong = EntityResolutionService._score(
        GeneratedEntityCandidate(person, 1.0, False),
        normalize_entity_name(EntityType.PERSON, "Juan Pérez"),
        {},
    )
    assert score >= 0.90
    assert strong is False
    assert signals["strong_person_context"] is False


def test_person_same_company_and_role_is_strong_context() -> None:
    person = entity(
        EntityType.PERSON,
        "Juan Pérez",
        context={"company": "acme", "role": "director"},
    )
    score, signals, strong = EntityResolutionService._score(
        GeneratedEntityCandidate(person, 1.0, False),
        normalize_entity_name(EntityType.PERSON, "Juan Pérez"),
        {"company": "ACME", "role": "Director"},
    )
    assert score == 1.0
    assert strong is True
    assert signals["context_agreement"] == ["company", "role"]
