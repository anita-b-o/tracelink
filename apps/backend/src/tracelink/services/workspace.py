from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.schemas.investigations import (
    InvestigationCountsRead,
    InvestigationProgressRead,
    InvestigationSummaryRead,
)
from tracelink.domain.enums import AssertionStatus, ResearchTaskStatus
from tracelink.domain.models import (
    EntityMention,
    Evidence,
    Investigation,
    InvestigationArtifact,
    Relationship,
    ResearchTask,
)


async def investigation_summaries(
    session: AsyncSession, investigations: list[Investigation]
) -> list[InvestigationSummaryRead]:
    ids = [item.id for item in investigations]
    if not ids:
        return []

    task_rows = (
        await session.execute(
            select(ResearchTask.investigation_id, ResearchTask.status, func.count())
            .where(ResearchTask.investigation_id.in_(ids))
            .group_by(ResearchTask.investigation_id, ResearchTask.status)
        )
    ).all()
    task_counts: dict[UUID, dict[ResearchTaskStatus, int]] = defaultdict(dict)
    for investigation_id, task_status, count in task_rows:
        task_counts[investigation_id][task_status] = int(count)

    entity_rows = (
        await session.execute(
            select(
                EntityMention.investigation_id, func.count(func.distinct(EntityMention.entity_id))
            )
            .where(EntityMention.investigation_id.in_(ids), EntityMention.entity_id.is_not(None))
            .group_by(EntityMention.investigation_id)
        )
    ).all()
    entity_counts = {key: int(value) for key, value in entity_rows}

    relationship_rows = (
        await session.execute(
            select(
                Evidence.investigation_id,
                func.count(func.distinct(Evidence.relationship_id)),
                func.count(func.distinct(Evidence.relationship_id)).filter(
                    Relationship.status == AssertionStatus.CONTRADICTED
                ),
            )
            .join(Relationship, Relationship.id == Evidence.relationship_id)
            .where(Evidence.investigation_id.in_(ids), Evidence.relationship_id.is_not(None))
            .group_by(Evidence.investigation_id)
        )
    ).all()
    relationship_counts = {
        key: (int(total), int(contradictions)) for key, total, contradictions in relationship_rows
    }

    artifact_rows = (
        await session.execute(
            select(
                InvestigationArtifact.investigation_id,
                func.count(func.distinct(InvestigationArtifact.source_id)),
                func.count(func.distinct(InvestigationArtifact.document_id)),
            )
            .where(InvestigationArtifact.investigation_id.in_(ids))
            .group_by(InvestigationArtifact.investigation_id)
        )
    ).all()
    artifact_counts = {
        key: (int(sources), int(documents)) for key, sources, documents in artifact_rows
    }

    summaries: list[InvestigationSummaryRead] = []
    for investigation in investigations:
        statuses = task_counts[investigation.id]
        total = sum(statuses.values())
        completed = statuses.get(ResearchTaskStatus.COMPLETED, 0)
        failed = statuses.get(ResearchTaskStatus.FAILED, 0)
        cancelled = statuses.get(ResearchTaskStatus.CANCELLED, 0)
        terminal = completed + failed + cancelled
        relationship_total, contradictions = relationship_counts.get(investigation.id, (0, 0))
        sources, documents = artifact_counts.get(investigation.id, (0, 0))
        summaries.append(
            InvestigationSummaryRead(
                id=investigation.id,
                title=investigation.title,
                original_query=investigation.original_query,
                status=investigation.status,
                created_at=investigation.created_at,
                updated_at=investigation.updated_at,
                progress=InvestigationProgressRead(
                    total=total,
                    pending=statuses.get(ResearchTaskStatus.PENDING, 0),
                    running=statuses.get(ResearchTaskStatus.RUNNING, 0),
                    completed=completed,
                    failed=failed,
                    cancelled=cancelled,
                    percent=round(terminal / total * 100) if total else 0,
                ),
                counts=InvestigationCountsRead(
                    tasks=total,
                    entities=entity_counts.get(investigation.id, 0),
                    relationships=relationship_total,
                    contradictions=contradictions,
                    sources=sources,
                    documents=documents,
                ),
            )
        )
    return summaries
