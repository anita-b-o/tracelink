from __future__ import annotations

import hashlib
import json
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.enums import (
    EntityType,
    InvestigationReportStatus,
    InvestigationReportType,
)
from tracelink.domain.models import (
    Document,
    Entity,
    EntityMention,
    Evidence,
    Investigation,
    InvestigationArtifact,
    InvestigationReport,
    Relationship,
)
from tracelink.domain.rag import RetrievalFilters
from tracelink.repositories.reports import InvestigationReportRepository
from tracelink.services.citations import CitationValidator
from tracelink.services.errors import DomainConflictError, DomainNotFoundError
from tracelink.services.grounded_context import GroundedContextBuilder
from tracelink.services.hybrid_retrieval import HybridRetriever
from tracelink.services.llm_providers import LLMProvider

REPORT_PROMPT_VERSION = "grounded-reports-v1"


def sort_partial_dates(values: list[str]) -> list[str]:
    def key(value: str) -> tuple[int, int, int, int]:
        parts = value.split("-")
        return (
            int(parts[0]),
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
            len(parts),
        )

    return sorted(values, key=key)


class InvestigationReportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        llm_provider: LLMProvider,
        retriever: HybridRetriever,
    ) -> None:
        self.session = session
        self.settings = settings
        self.llm_provider = llm_provider
        self.retriever = retriever
        self.repository = InvestigationReportRepository(session)

    async def _subject(self, investigation_id: UUID, subject_id: UUID | None) -> Entity | None:
        if subject_id is None:
            return None
        return cast(
            Entity | None,
            await self.session.scalar(
                select(Entity)
                .join(EntityMention, EntityMention.entity_id == Entity.id)
                .where(
                    Entity.id == subject_id,
                    EntityMention.investigation_id == investigation_id,
                )
            ),
        )

    async def fingerprint(
        self,
        investigation_id: UUID,
        report_type: InvestigationReportType,
        subject_entity_id: UUID | None,
    ) -> str:
        investigation = await self.session.get(Investigation, investigation_id)
        if investigation is None:
            raise DomainNotFoundError("investigation not found")
        documents = list(
            await self.session.scalars(
                select(Document)
                .join(InvestigationArtifact, InvestigationArtifact.document_id == Document.id)
                .where(InvestigationArtifact.investigation_id == investigation_id)
                .order_by(Document.id)
            )
        )
        evidence = list(
            await self.session.scalars(
                select(Evidence)
                .where(Evidence.investigation_id == investigation_id)
                .order_by(Evidence.id)
            )
        )
        relationships = list(
            await self.session.scalars(
                select(Relationship)
                .join(Evidence, Evidence.relationship_id == Relationship.id)
                .where(Evidence.investigation_id == investigation_id)
                .distinct()
                .order_by(Relationship.id)
            )
        )
        payload = {
            "investigation_id": str(investigation_id),
            "type": report_type.value,
            "subject_entity_id": str(subject_entity_id) if subject_entity_id else None,
            "documents": [(str(item.id), item.content_hash) for item in documents],
            "evidence": [(str(item.id), item.fingerprint) for item in evidence],
            "relationships": [
                (
                    str(item.id),
                    item.status.value,
                    item.temporal_start,
                    item.temporal_end,
                    item.updated_at.isoformat(),
                )
                for item in relationships
            ],
            "provider": self.llm_provider.provider_name,
            "model": self.llm_provider.model_name,
            "prompt_version": REPORT_PROMPT_VERSION,
            "rag": {
                "top_k": self.settings.rag_top_k,
                "max_context_chars": self.settings.rag_max_context_chars,
                "semantic_weight": self.settings.rag_semantic_weight,
                "lexical_weight": self.settings.rag_lexical_weight,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def request(
        self,
        investigation_id: UUID,
        report_type: InvestigationReportType,
        subject_entity_id: UUID | None,
    ) -> InvestigationReport:
        subject = await self._subject(investigation_id, subject_entity_id)
        if report_type is InvestigationReportType.CORPORATE_PROFILE:
            if subject is None or subject.type not in {EntityType.COMPANY, EntityType.ORGANIZATION}:
                raise DomainConflictError(
                    "CORPORATE_PROFILE requires a COMPANY or ORGANIZATION in the investigation"
                )
        elif subject_entity_id is not None and subject is None:
            raise DomainNotFoundError("subject entity is not part of the investigation")
        fingerprint = await self.fingerprint(investigation_id, report_type, subject_entity_id)
        report = await self.repository.get_or_create(
            investigation_id=investigation_id,
            report_type=report_type,
            subject_entity_id=subject_entity_id,
            fingerprint=fingerprint,
            provider=self.llm_provider.provider_name,
            model=self.llm_provider.model_name,
            prompt_version=REPORT_PROMPT_VERSION,
            parameters={"subject_entity_id": str(subject_entity_id) if subject_entity_id else None},
        )
        if report.status is InvestigationReportStatus.FAILED:
            report.status = InvestigationReportStatus.PENDING
            report.last_error_code = None
            report.last_error_message = None
        await self.session.flush()
        return report

    async def generate(self, report_id: UUID, celery_task_id: str) -> InvestigationReport:
        report = await self.repository.get(report_id, for_update=True)
        if report is None:
            raise DomainNotFoundError("report not found")
        if report.status is InvestigationReportStatus.COMPLETED:
            return report
        report.status = InvestigationReportStatus.RUNNING
        report.active_celery_task_id = celery_task_id
        report.attempts += 1
        await self.session.flush()

        investigation = await self.session.get(Investigation, report.investigation_id)
        assert investigation is not None
        subject = await self._subject(report.investigation_id, report.subject_entity_id)
        query = investigation.original_query
        filters = RetrievalFilters()
        if subject is not None:
            query = subject.canonical_name
            filters = RetrievalFilters(entity_ids=(subject.id,))
        else:
            entity_names = list(
                await self.session.scalars(
                    select(Entity.canonical_name)
                    .join(EntityMention, EntityMention.entity_id == Entity.id)
                    .where(EntityMention.investigation_id == report.investigation_id)
                    .distinct()
                    .order_by(Entity.canonical_name)
                    .limit(20)
                )
            )
            if entity_names:
                query = " ".join((query, *entity_names))
        hits = await self.retriever.search(
            report.investigation_id, query, filters=filters, top_k=self.settings.rag_top_k
        )
        context = await GroundedContextBuilder(self.session, self.settings).build(
            report.investigation_id, hits
        )
        if (
            not hits
            or hits[0].combined_score < self.settings.rag_min_retrieval_score
            or context.evidence_count < self.settings.rag_min_evidence_count
        ):
            report.content = {
                "title": report.type.value.replace("_", " ").title(),
                "abstained": True,
                "executive_summary": "",
                "sections": [],
                "key_entities": [],
                "key_relationships": [],
                "timeline": [],
                "contradictions": context.contradictions,
                "limitations": ["No hay evidencia suficiente para generar el reporte."],
                "citations": [],
            }
        else:
            generated = await self.llm_provider.generate_report(
                report.type.value,
                context,
                subject.canonical_name if subject else None,
            )
            claims = list(generated.summary_claims)
            for section in generated.sections:
                claims.extend(section.claims)
            await CitationValidator(self.session).validate_claims(context, claims)
            citation_ids: list[str] = []
            for claim in claims:
                for ref in claim.citation_ids:
                    if ref not in citation_ids:
                        citation_ids.append(ref)
            timeline_items: dict[tuple[str, str], dict[str, str]] = {}
            for relationship in context.payload.get("relationships", []):
                if isinstance(relationship, dict):
                    for field, kind in (
                        ("temporal_start", "RELATIONSHIP_START"),
                        ("temporal_end", "RELATIONSHIP_END"),
                    ):
                        value = relationship.get(field)
                        if isinstance(value, str):
                            timeline_items[(value, kind)] = {"date": value, "kind": kind}
            for claim in context.payload.get("relationship_claims", []):
                if not isinstance(claim, dict):
                    continue
                claim_kind = claim.get("claim_kind")
                for field, default_kind in (
                    ("temporal_start", "CLAIM_START"),
                    ("temporal_end", "CLAIM_END"),
                ):
                    value = claim.get(field)
                    if isinstance(value, str):
                        kind = "RELATIONSHIP_END" if claim_kind == "ENDS" else default_kind
                        timeline_items[(value, kind)] = {"date": value, "kind": kind}
            for hit in context.hits:
                if hit.published_at is not None:
                    value = hit.published_at.date().isoformat()
                    timeline_items[(value, "SOURCE_PUBLISHED")] = {
                        "date": value,
                        "kind": "SOURCE_PUBLISHED",
                    }
            ordered_dates = sort_partial_dates(list({date for date, _ in timeline_items}))
            report.content = {
                "title": generated.title,
                "abstained": False,
                "executive_summary": " ".join(claim.text for claim in generated.summary_claims),
                "summary_claims": [
                    claim.model_dump(mode="json") for claim in generated.summary_claims
                ],
                "sections": [section.model_dump(mode="json") for section in generated.sections],
                "key_entities": context.payload.get("entities", []),
                "key_relationships": context.payload.get("relationships", []),
                "timeline": [
                    timeline_items[(date, kind)]
                    for date in ordered_dates
                    for candidate_date, kind in sorted(timeline_items)
                    if candidate_date == date
                ],
                "contradictions": context.contradictions,
                "limitations": generated.limitations,
                "citations": [
                    {"id": ref, **context.allowed_citations[ref]} for ref in citation_ids
                ],
            }
        report.status = InvestigationReportStatus.COMPLETED
        report.active_celery_task_id = None
        report.last_error_code = None
        report.last_error_message = None
        await self.session.flush()
        return report

    async def fail(self, report_id: UUID, *, code: str, message: str) -> None:
        report = await self.repository.get(report_id, for_update=True)
        if report is None or report.status is InvestigationReportStatus.COMPLETED:
            return
        report.status = InvestigationReportStatus.FAILED
        report.active_celery_task_id = None
        report.last_error_code = code
        report.last_error_message = message
        await self.session.flush()
