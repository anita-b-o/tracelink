from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import AssertionStatus
from tracelink.domain.models import Finding
from tracelink.domain.validation import require_non_empty, validate_confidence


class FindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        investigation_id: UUID,
        title: str,
        description: str,
        confidence: float,
        status: AssertionStatus,
        relevance: float | None = None,
    ) -> Finding:
        validate_confidence(confidence)
        if relevance is not None:
            validate_confidence(relevance, "relevance")
        finding = Finding(
            investigation_id=investigation_id,
            title=require_non_empty(title.strip(), "title"),
            description=require_non_empty(description.strip(), "description"),
            confidence=confidence,
            status=status,
            relevance=relevance,
        )
        self.session.add(finding)
        await self.session.flush()
        await self.session.refresh(finding)
        return finding

    async def get_by_id(self, finding_id: UUID) -> Finding | None:
        return await self.session.get(Finding, finding_id)

    async def list(
        self,
        *,
        investigation_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Finding]:
        statement = select(Finding)
        if investigation_id is not None:
            statement = statement.where(Finding.investigation_id == investigation_id)
        result = await self.session.scalars(
            statement.order_by(Finding.created_at.desc(), Finding.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def update(
        self,
        finding: Finding,
        *,
        title: str | None = None,
        description: str | None = None,
        confidence: float | None = None,
        status: AssertionStatus | None = None,
        relevance: float | None = None,
    ) -> Finding:
        if title is not None:
            finding.title = title
        if description is not None:
            finding.description = description
        if confidence is not None:
            validate_confidence(confidence)
            finding.confidence = confidence
        if status is not None:
            finding.status = status
        if relevance is not None:
            validate_confidence(relevance, "relevance")
            finding.relevance = relevance
        await self.session.flush()
        await self.session.refresh(finding)
        return finding
