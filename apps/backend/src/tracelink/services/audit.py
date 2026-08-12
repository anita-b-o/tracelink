from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.domain.models import AuditEvent, JsonObject


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        user_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        metadata: JsonObject | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_=metadata or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event
