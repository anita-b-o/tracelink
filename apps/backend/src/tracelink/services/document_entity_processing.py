from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.entity_extraction import (
    EntityExtractionProvider,
    ExtractedEntityCandidate,
    ExtractionContext,
)
from tracelink.domain.enums import EntityType
from tracelink.domain.models import Document, EntityMention
from tracelink.domain.normalization import normalize_entity_name
from tracelink.repositories.entity_mentions import EntityMentionRepository
from tracelink.repositories.investigation_artifacts import InvestigationArtifactRepository
from tracelink.services.deterministic_entity_extraction import extract_deterministic
from tracelink.services.document_preprocessing import DocumentChunk, chunk_document
from tracelink.services.entity_resolution import EntityResolutionService
from tracelink.services.errors import DomainNotFoundError

logger = logging.getLogger(__name__)
ALLOWED_ENTITY_TYPES = frozenset(
    {
        EntityType.PERSON,
        EntityType.COMPANY,
        EntityType.ORGANIZATION,
        EntityType.DOMAIN,
        EntityType.ADDRESS,
    }
)
MIN_RESOLVABLE_EXTRACTION_CONFIDENCE = 0.50


@dataclass(slots=True)
class PreparedMention:
    type: EntityType
    surface_form: str
    canonical_name_candidate: str
    normalized_form: str
    confidence: float
    start_offset: int | None
    end_offset: int | None
    chunk_index: int
    attributes: dict[str, JsonValue]
    methods: set[str]
    reasoning_signals: set[str]
    type_conflict: bool = False


def _document_lock_key(investigation_id: UUID, document_id: UUID) -> int:
    digest = hashlib.sha256(f"{investigation_id}:{document_id}".encode()).digest()
    return int.from_bytes(digest[:8], signed=True)


def _fingerprint(prepared: PreparedMention) -> str:
    locator = (
        f"{prepared.start_offset}:{prepared.end_offset}"
        if prepared.start_offset is not None
        else f"chunk:{prepared.chunk_index}:{prepared.surface_form.casefold()}"
    )
    value = f"{prepared.type.value}|{prepared.normalized_form}|{locator}"
    return hashlib.sha256(value.encode()).hexdigest()


def _prepare_candidate(
    candidate: ExtractedEntityCandidate,
    chunk: DocumentChunk,
    method: str,
) -> PreparedMention:
    normalized = normalize_entity_name(candidate.type, candidate.canonical_name_candidate)
    start_offset: int | None = None
    end_offset: int | None = None
    if candidate.start_offset is not None and candidate.end_offset is not None:
        start_offset, end_offset = chunk.to_document_offsets(
            candidate.start_offset, candidate.end_offset
        )
    return PreparedMention(
        type=candidate.type,
        surface_form=candidate.surface_form,
        canonical_name_candidate=normalized.canonical,
        normalized_form=normalized.comparison_key,
        confidence=candidate.confidence,
        start_offset=start_offset,
        end_offset=end_offset,
        chunk_index=chunk.index,
        attributes=dict(candidate.attributes),
        methods={method},
        reasoning_signals=set(candidate.reasoning_signals),
    )


class DocumentEntityProcessingService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: EntityExtractionProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.provider = provider
        self.mentions = EntityMentionRepository(session)

    async def _extract(self, investigation_id: UUID, document: Document) -> list[PreparedMention]:
        chunks = chunk_document(
            document.raw_text,
            chunk_size=self.settings.entity_extraction_chunk_size,
            overlap=self.settings.entity_extraction_chunk_overlap,
        )
        prepared: dict[tuple[object, ...], PreparedMention] = {}
        for chunk in chunks:
            extracted: list[tuple[str, ExtractedEntityCandidate]] = [
                ("deterministic", candidate)
                for candidate in extract_deterministic(chunk.text, ALLOWED_ENTITY_TYPES)
            ]
            if self.provider is not None:
                provider_candidates = await self.provider.extract(
                    chunk.text,
                    ALLOWED_ENTITY_TYPES,
                    ExtractionContext(
                        investigation_id=investigation_id,
                        document_id=document.id,
                        chunk_index=chunk.index,
                    ),
                )
                extracted.extend(
                    (self.provider.name, candidate) for candidate in provider_candidates
                )
            for method, candidate in extracted:
                try:
                    item = _prepare_candidate(candidate, chunk, method)
                except ValueError:
                    logger.warning(
                        "entity extraction candidate rejected",
                        extra={
                            "investigation_id": str(investigation_id),
                            "document_id": str(document.id),
                            "entity_type": candidate.type.value,
                            "extraction_method": method,
                        },
                    )
                    continue
                locator: tuple[object, ...] = (
                    (item.start_offset, item.end_offset)
                    if item.start_offset is not None
                    else (item.chunk_index, item.surface_form.casefold())
                )
                key = (item.type, item.normalized_form, *locator)
                existing = prepared.get(key)
                if existing is None:
                    prepared[key] = item
                else:
                    existing.methods.update(item.methods)
                    existing.reasoning_signals.update(item.reasoning_signals)
                    if item.confidence > existing.confidence:
                        existing.confidence = item.confidence
                        existing.canonical_name_candidate = item.canonical_name_candidate
                        existing.attributes = item.attributes

        types_by_locator: dict[tuple[object, ...], set[EntityType]] = {}
        for item in prepared.values():
            locator = (
                (item.start_offset, item.end_offset)
                if item.start_offset is not None
                else (item.chunk_index, item.surface_form.casefold())
            )
            types_by_locator.setdefault(locator, set()).add(item.type)
        for item in prepared.values():
            locator = (
                (item.start_offset, item.end_offset)
                if item.start_offset is not None
                else (item.chunk_index, item.surface_form.casefold())
            )
            item.type_conflict = len(types_by_locator[locator]) > 1
        return list(prepared.values())

    async def process(self, investigation_id: UUID, document_id: UUID) -> list[EntityMention]:
        if not await InvestigationArtifactRepository(self.session).has_document(
            investigation_id, document_id
        ):
            raise DomainNotFoundError("document is not associated with investigation")
        document = await self.session.get(Document, document_id)
        if document is None:
            raise DomainNotFoundError("document not found")
        await self.session.execute(
            select(func.pg_advisory_xact_lock(_document_lock_key(investigation_id, document_id)))
        )
        prepared_mentions = await self._extract(investigation_id, document)
        stored_mentions: list[EntityMention] = []
        resolver = EntityResolutionService(self.session, self.settings)
        for prepared in prepared_mentions:
            fingerprint = _fingerprint(prepared)
            mention = await self.mentions.get_by_fingerprint(
                investigation_id, document_id, fingerprint
            )
            if mention is not None:
                stored_mentions.append(mention)
                continue
            metadata: dict[str, Any] = {
                "extraction_methods": sorted(prepared.methods),
                "attributes": prepared.attributes,
                "reasoning_signals": sorted(prepared.reasoning_signals),
                "type_conflict": prepared.type_conflict,
            }
            primary_method = sorted(prepared.methods)[0]
            mention = await self.mentions.create(
                investigation_id=investigation_id,
                document_id=document_id,
                entity_type=prepared.type,
                surface_form=prepared.surface_form,
                normalized_form=prepared.normalized_form,
                start_offset=prepared.start_offset,
                end_offset=prepared.end_offset,
                chunk_index=prepared.chunk_index,
                extraction_method=primary_method,
                confidence=prepared.confidence,
                fingerprint=fingerprint,
                metadata=metadata,
            )
            if (
                prepared.confidence >= MIN_RESOLVABLE_EXTRACTION_CONFIDENCE
                and not prepared.type_conflict
            ):
                decision = await resolver.resolve(
                    mention,
                    canonical_name_candidate=prepared.canonical_name_candidate,
                    attributes=prepared.attributes,
                )
                logger.info(
                    "entity mention resolved",
                    extra={
                        "investigation_id": str(investigation_id),
                        "document_id": str(document_id),
                        "entity_mention_id": str(mention.id),
                        "entity_id": str(decision.entity_id) if decision.entity_id else None,
                        "entity_type": mention.entity_type.value,
                        "resolution_decision": decision.decision.value,
                        "resolution_score": decision.score,
                        "extraction_method": primary_method,
                    },
                )
            stored_mentions.append(mention)
        await self.session.flush()
        return stored_mentions
