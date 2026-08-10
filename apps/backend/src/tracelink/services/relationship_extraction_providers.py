from __future__ import annotations

from collections.abc import Mapping

from tracelink.domain.enums import RelationshipType
from tracelink.domain.relationship_extraction import (
    ExtractedRelationshipCandidate,
    RelationshipExtractionContext,
    RelationshipExtractionProvider,
    RelationshipExtractionProviderError,
    RelationshipProviderOutputError,
    ResolvedRelationshipMention,
    TransientRelationshipExtractionProviderError,
)


class FakeRelationshipExtractionProvider:
    name = "fake"

    def __init__(
        self,
        responses: Mapping[str, list[ExtractedRelationshipCandidate]] | None = None,
        *,
        fail_for: frozenset[str] = frozenset(),
        transient_fail_for: frozenset[str] = frozenset(),
        invalid_for: frozenset[str] = frozenset(),
    ) -> None:
        self.responses = dict(responses or {})
        self.fail_for = fail_for
        self.transient_fail_for = transient_fail_for
        self.invalid_for = invalid_for

    async def extract(
        self,
        text: str,
        mentions: list[ResolvedRelationshipMention],
        allowed_types: frozenset[RelationshipType],
        context: RelationshipExtractionContext,
    ) -> list[ExtractedRelationshipCandidate]:
        _ = (mentions, context)
        if text in self.transient_fail_for:
            raise TransientRelationshipExtractionProviderError(
                "fake relationship extraction failed transiently"
            )
        if text in self.fail_for:
            raise RelationshipExtractionProviderError("fake relationship extraction failed")
        if text in self.invalid_for:
            raise RelationshipProviderOutputError("fake relationship output is invalid")
        return [
            candidate
            for candidate in self.responses.get(text, [])
            if candidate.type in allowed_types
        ]


def get_relationship_extraction_provider() -> RelationshipExtractionProvider | None:
    return None
