from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.connectors.models import ConnectorOutput, ResearchTaskResult, SourceArtifact
from tracelink.domain.models import Source
from tracelink.domain.normalization import sha256_text
from tracelink.repositories.documents import DocumentRepository
from tracelink.repositories.investigation_artifacts import InvestigationArtifactRepository
from tracelink.repositories.sources import SourceRepository
from tracelink.services.documents import DocumentService


def _advisory_lock_key(url_hash: str) -> int:
    value = int(url_hash[:16], 16)
    return value - 2**64 if value >= 2**63 else value


class ResearchArtifactService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sources = SourceRepository(session)
        self.documents = DocumentService(session, DocumentRepository(session))
        self.investigation_artifacts = InvestigationArtifactRepository(session)

    async def _get_or_create_source(self, artifact: SourceArtifact) -> Source:
        url_hash = sha256_text(artifact.normalized_url)
        await self.session.execute(select(func.pg_advisory_xact_lock(_advisory_lock_key(url_hash))))
        existing = await self.sources.find_by_url(artifact.normalized_url)
        if existing:
            source = existing[0]
            source.publisher = source.publisher or artifact.publisher
            source.title = source.title or artifact.title
            source.published_at = source.published_at or artifact.published_at
            source.retrieved_at = max(source.retrieved_at, artifact.retrieved_at)
            source.metadata_ = {**source.metadata_, **artifact.metadata}
            await self.session.flush()
            return source
        return await self.sources.create(
            source_type=artifact.source_type,
            url=artifact.url,
            normalized_url=artifact.normalized_url,
            publisher=artifact.publisher,
            title=artifact.title,
            published_at=artifact.published_at,
            retrieved_at=artifact.retrieved_at,
            metadata=artifact.metadata,
        )

    async def persist(self, investigation_id: UUID, output: ConnectorOutput) -> ResearchTaskResult:
        sources_by_url: dict[str, Source] = {}
        source_ids: list[UUID] = []
        document_ids: list[UUID] = []
        document_urls = {artifact.source_normalized_url for artifact in output.documents}
        for source_artifact in output.sources:
            source = await self._get_or_create_source(source_artifact)
            sources_by_url[source_artifact.normalized_url] = source
            if source.id not in source_ids:
                source_ids.append(source.id)
            if source_artifact.normalized_url not in document_urls:
                await self.investigation_artifacts.associate(
                    investigation_id=investigation_id,
                    source_id=source.id,
                    document_id=None,
                )
        for document_artifact in output.documents:
            source = sources_by_url[document_artifact.source_normalized_url]
            document = await self.documents.create(
                source_id=source.id,
                mime_type=document_artifact.mime_type,
                raw_text=document_artifact.raw_text,
                metadata=document_artifact.metadata,
            )
            if document.id not in document_ids:
                document_ids.append(document.id)
            await self.investigation_artifacts.associate(
                investigation_id=investigation_id,
                source_id=source.id,
                document_id=document.id,
            )
        return ResearchTaskResult(
            connector=output.connector,
            status=output.status,
            source_ids=source_ids,
            document_ids=document_ids,
            result_count=output.result_count,
            metadata=output.metadata,
        )
