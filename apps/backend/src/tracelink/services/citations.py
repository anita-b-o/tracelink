from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import Evidence, InvestigationArtifact, RetrievalChunk
from tracelink.domain.rag import GroundedClaim, GroundedContext


class InvalidCitationError(ValueError):
    pass


class CitationValidator:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def validate_claims(
        self, context: GroundedContext, claims: list[GroundedClaim]
    ) -> list[GroundedClaim]:
        if not claims:
            raise InvalidCitationError("grounded output requires at least one cited claim")
        for claim in claims:
            if not claim.citation_ids:
                raise InvalidCitationError("every factual claim requires a citation")
            if len(claim.citation_ids) != len(set(claim.citation_ids)):
                raise InvalidCitationError("duplicate citation IDs are not allowed")
            for ref in claim.citation_ids:
                if ref not in context.allowed_citations:
                    raise InvalidCitationError("citation was not supplied in the grounded context")
                await self._validate_membership(context.investigation_id, ref)
        return claims

    async def _validate_membership(self, investigation_id: UUID, ref: str) -> None:
        try:
            kind, raw_id = ref.split(":", 1)
            identifier = UUID(raw_id)
        except (ValueError, TypeError) as exc:
            raise InvalidCitationError("citation ID is malformed") from exc
        if kind == "EVIDENCE":
            valid = await self.session.scalar(
                select(Evidence.id).where(
                    Evidence.id == identifier,
                    Evidence.investigation_id == investigation_id,
                )
            )
        elif kind == "CHUNK":
            valid = await self.session.scalar(
                select(RetrievalChunk.id)
                .join(
                    InvestigationArtifact,
                    InvestigationArtifact.document_id == RetrievalChunk.document_id,
                )
                .where(
                    RetrievalChunk.id == identifier,
                    InvestigationArtifact.investigation_id == investigation_id,
                )
            )
        elif kind == "DOCUMENT":
            valid = await self.session.scalar(
                select(InvestigationArtifact.id).where(
                    InvestigationArtifact.investigation_id == investigation_id,
                    InvestigationArtifact.document_id == identifier,
                )
            )
        elif kind == "SOURCE":
            valid = await self.session.scalar(
                select(InvestigationArtifact.id).where(
                    InvestigationArtifact.investigation_id == investigation_id,
                    InvestigationArtifact.source_id == identifier,
                )
            )
        else:
            raise InvalidCitationError("citation type is not allowed")
        if valid is None:
            raise InvalidCitationError("citation does not belong to the investigation")
