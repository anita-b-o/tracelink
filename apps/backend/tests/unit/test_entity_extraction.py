from uuid import uuid4

import pytest
from pydantic import ValidationError

from tracelink.domain.entity_extraction import (
    ExtractedEntityCandidate,
    ExtractionContext,
)
from tracelink.domain.enums import EntityType
from tracelink.domain.normalization import (
    normalize_address,
    normalize_company,
    normalize_domain,
    normalize_organization,
    normalize_person,
)
from tracelink.services.deterministic_entity_extraction import extract_deterministic
from tracelink.services.document_preprocessing import chunk_document
from tracelink.services.entity_extraction_providers import FakeEntityExtractionProvider


def test_type_specific_normalizers() -> None:
    assert normalize_person("  Juan   Carlos Pérez ").comparison_key == "juan carlos pérez"
    assert normalize_company("ACME S.A.").comparison_key == "acme"
    assert normalize_company("Acme Sociedad Anónima").comparison_key == "acme"
    assert normalize_organization("Fundación Uno S.A.").comparison_key == "fundación uno"
    assert normalize_domain("MÜNICH.Example.").canonical == "xn--mnich-kva.example"
    assert normalize_address("Avenida Siempre Viva 742").comparison_key == "av siempre viva 742"


@pytest.mark.parametrize("value", ["localhost", "https://example.com", "bad..example"])
def test_domain_normalizer_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(value)


def test_chunking_is_reproducible_overlapping_and_preserves_offsets() -> None:
    text = ("Primera oración con datos. " * 80) + "example.com"
    first = chunk_document(text, chunk_size=500, overlap=50)
    second = chunk_document(text, chunk_size=500, overlap=50)
    assert first == second
    assert all(chunk.text == text[chunk.start_offset : chunk.end_offset] for chunk in first)
    assert all(len(chunk.text) >= 300 for chunk in first[:-1])
    assert first[1].start_offset < first[0].end_offset


def test_deterministic_extractors_return_structured_candidates() -> None:
    text = (
        "La empresa ACME S.A. opera example.com. "
        "Dr. Juan Pérez vive en Avenida Siempre Viva 742. "
        "Fundación Horizonte Abierto publicó el aviso."
    )
    candidates = extract_deterministic(
        text,
        frozenset(
            {
                EntityType.DOMAIN,
                EntityType.COMPANY,
                EntityType.PERSON,
                EntityType.ADDRESS,
                EntityType.ORGANIZATION,
            }
        ),
    )
    types = {candidate.type for candidate in candidates}
    assert {
        EntityType.DOMAIN,
        EntityType.COMPANY,
        EntityType.PERSON,
        EntityType.ADDRESS,
        EntityType.ORGANIZATION,
    } <= types
    assert all(candidate.start_offset is not None for candidate in candidates)


@pytest.mark.asyncio
async def test_fake_provider_is_deterministic_configurable_and_filters_types() -> None:
    response = ExtractedEntityCandidate(
        type=EntityType.PERSON,
        surface_form="Alex Kim",
        canonical_name_candidate="Alex Kim",
        confidence=0.72,
        attributes={"company": "One"},
    )
    provider = FakeEntityExtractionProvider({"text": [response, response]})
    context = ExtractionContext(investigation_id=uuid4(), document_id=uuid4(), chunk_index=0)
    first = await provider.extract("text", frozenset({EntityType.PERSON}), context)
    second = await provider.extract("text", frozenset({EntityType.PERSON}), context)
    assert first == second == [response, response]
    assert await provider.extract("text", frozenset({EntityType.COMPANY}), context) == []


def test_extracted_candidate_validates_confidence_offsets_and_document_type() -> None:
    with pytest.raises(ValidationError):
        ExtractedEntityCandidate(
            type=EntityType.PERSON,
            surface_form="Name",
            canonical_name_candidate="Name",
            confidence=1.1,
        )
    with pytest.raises(ValidationError):
        ExtractedEntityCandidate(
            type=EntityType.PERSON,
            surface_form="Name",
            canonical_name_candidate="Name",
            confidence=0.8,
            start_offset=3,
        )
    with pytest.raises(ValidationError):
        ExtractedEntityCandidate(
            type=EntityType.DOCUMENT,
            surface_form="Document",
            canonical_name_candidate="Document",
            confidence=0.8,
        )
