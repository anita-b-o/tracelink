from uuid import uuid4

import pytest
from pydantic import ValidationError

from tracelink.api.schemas.entities import EntityCreate
from tracelink.domain.validation import (
    validate_confidence,
    validate_evidence_target,
    validate_relationship_endpoints,
)


@pytest.mark.parametrize("value", [-0.01, 1.01, float("inf"), float("nan")])
def test_confidence_rejects_out_of_range_or_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_confidence(value)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_confidence_accepts_closed_interval(value: float) -> None:
    assert validate_confidence(value) == value


def test_relationship_rejects_self_reference() -> None:
    entity_id = uuid4()
    with pytest.raises(ValueError, match="same entity"):
        validate_relationship_endpoints(entity_id, entity_id)


def test_evidence_requires_a_target() -> None:
    with pytest.raises(ValueError, match="entity or a relationship"):
        validate_evidence_target(None, None)


def test_pydantic_rejects_unknown_enum() -> None:
    with pytest.raises(ValidationError):
        EntityCreate.model_validate({"type": "UNKNOWN", "canonical_name": "ACME"})
