import math
from datetime import datetime
from uuid import UUID


def require_non_empty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


def validate_confidence(value: float, field_name: str = "confidence") -> float:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


def validate_relationship_endpoints(source_entity_id: UUID, target_entity_id: UUID) -> None:
    if source_entity_id == target_entity_id:
        raise ValueError("a relationship cannot reference the same entity twice")


def validate_evidence_target(entity_id: UUID | None, relationship_id: UUID | None) -> None:
    if entity_id is None and relationship_id is None:
        raise ValueError("evidence must reference an entity or a relationship")


def validate_chronology(
    first: datetime | None,
    last: datetime | None,
    first_name: str,
    last_name: str,
) -> None:
    if first is not None and last is not None and last < first:
        raise ValueError(f"{last_name} cannot be earlier than {first_name}")
