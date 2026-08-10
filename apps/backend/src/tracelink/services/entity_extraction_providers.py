from __future__ import annotations

from collections.abc import Mapping

from tracelink.domain.entity_extraction import (
    EntityExtractionProviderError,
    ExtractedEntityCandidate,
    ExtractionContext,
)
from tracelink.domain.enums import EntityType


class FakeEntityExtractionProvider:
    name = "fake"

    def __init__(
        self,
        responses: Mapping[str, list[ExtractedEntityCandidate]] | None = None,
        *,
        fail_for: frozenset[str] = frozenset(),
    ) -> None:
        self.responses = dict(responses or {})
        self.fail_for = fail_for

    async def extract(
        self,
        text: str,
        allowed_types: frozenset[EntityType],
        context: ExtractionContext,
    ) -> list[ExtractedEntityCandidate]:
        _ = context
        if text in self.fail_for:
            raise EntityExtractionProviderError("fake entity extraction failed")
        return [
            candidate
            for candidate in self.responses.get(text, [])
            if candidate.type in allowed_types
        ]
