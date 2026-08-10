from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.enums import InvestigationReportStatus, InvestigationReportType
from tracelink.domain.models import InvestigationReport, JsonObject


class InvestigationReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, report_id: UUID, *, for_update: bool = False) -> InvestigationReport | None:
        statement = select(InvestigationReport).where(InvestigationReport.id == report_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(InvestigationReport | None, await self.session.scalar(statement))

    async def get_or_create(
        self,
        *,
        investigation_id: UUID,
        report_type: InvestigationReportType,
        subject_entity_id: UUID | None,
        fingerprint: str,
        provider: str,
        model: str,
        prompt_version: str,
        parameters: JsonObject,
    ) -> InvestigationReport:
        report_id = uuid4()
        statement = (
            insert(InvestigationReport)
            .values(
                id=report_id,
                investigation_id=investigation_id,
                type=report_type,
                subject_entity_id=subject_entity_id,
                status=InvestigationReportStatus.PENDING,
                input_fingerprint=fingerprint,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                parameters=parameters,
                attempts=0,
            )
            .on_conflict_do_nothing(constraint="uq_investigation_report_fingerprint")
        )
        await self.session.execute(statement)
        report = await self.session.scalar(
            select(InvestigationReport).where(
                InvestigationReport.investigation_id == investigation_id,
                InvestigationReport.type == report_type,
                InvestigationReport.subject_entity_id.is_not_distinct_from(subject_entity_id),
                InvestigationReport.input_fingerprint == fingerprint,
            )
        )
        assert report is not None
        return report

    async def list_by_investigation(
        self, investigation_id: UUID, *, limit: int, offset: int
    ) -> list[InvestigationReport]:
        return list(
            await self.session.scalars(
                select(InvestigationReport)
                .where(InvestigationReport.investigation_id == investigation_id)
                .order_by(InvestigationReport.created_at.desc(), InvestigationReport.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
