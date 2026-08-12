from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from tracelink.core.config import get_settings
from tracelink.domain.enums import InvestigationReportStatus, OutboxStatus, ResearchTaskStatus
from tracelink.domain.models import (
    Investigation,
    InvestigationReport,
    OutboxEvent,
    ResearchTask,
    User,
)
from tracelink.infrastructure.database import close_database, get_session_factory
from tracelink.services.auth import normalize_email, password_hash


async def bootstrap_dev_user() -> None:
    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("bootstrap-dev-user is forbidden outside development/test")
    email = normalize_email(settings.dev_bootstrap_email)
    async with get_session_factory()() as session, session.begin():
        user = await session.scalar(select(User).where(User.email == email).with_for_update())
        if user is None:
            user = User(
                email=email,
                password_hash=password_hash.hash(
                    settings.dev_bootstrap_password.get_secret_value()
                ),
                display_name="TraceLink Developer",
                is_active=True,
            )
            session.add(user)
            await session.flush()
        legacy_count = int(
            await session.scalar(
                select(func.count(Investigation.id)).where(Investigation.user_id.is_(None))
            )
            or 0
        )
        await session.execute(
            update(Investigation).where(Investigation.user_id.is_(None)).values(user_id=user.id)
        )
    print(json.dumps({"user_id": str(user.id), "legacy_assigned": legacy_count}))


async def diagnose(*, apply: bool, stale_minutes: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(minutes=stale_minutes)
    settings = get_settings()
    async with get_session_factory()() as session, session.begin():
        stale_tasks = list(
            await session.scalars(
                select(ResearchTask).where(
                    ResearchTask.status == ResearchTaskStatus.RUNNING,
                    ResearchTask.started_at < cutoff,
                )
            )
        )
        stale_reports = list(
            await session.scalars(
                select(InvestigationReport).where(
                    InvestigationReport.status == InvestigationReportStatus.RUNNING,
                    InvestigationReport.updated_at < cutoff,
                )
            )
        )
        lease_cutoff = datetime.now(UTC) - timedelta(seconds=settings.outbox_lease_seconds)
        stale_outbox = list(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.status == OutboxStatus.PUBLISHING,
                    OutboxEvent.locked_at < lease_cutoff,
                )
            )
        )
        if apply:
            for task in stale_tasks:
                task.status = ResearchTaskStatus.FAILED
                task.last_error_code = "STUCK_TASK_RECOVERED"
                task.last_error_message = "task exceeded the operational running threshold"
                task.completed_at = datetime.now(UTC)
                task.active_celery_task_id = None
            for report in stale_reports:
                report.status = InvestigationReportStatus.FAILED
                report.last_error_code = "STUCK_REPORT_RECOVERED"
                report.last_error_message = "report exceeded the operational running threshold"
                report.active_celery_task_id = None
            for event in stale_outbox:
                event.status = OutboxStatus.FAILED
                event.locked_at = None
                event.next_attempt_at = datetime.now(UTC)
    print(
        json.dumps(
            {
                "applied": apply,
                "stale_research_tasks": len(stale_tasks),
                "stale_reports": len(stale_reports),
                "expired_outbox_leases": len(stale_outbox),
            }
        )
    )


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="TraceLink operational maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("bootstrap-dev-user")
    recovery = subparsers.add_parser("diagnose")
    recovery.add_argument("--apply", action="store_true")
    recovery.add_argument("--stale-minutes", type=int, default=60)
    args = parser.parse_args()
    try:
        if args.command == "bootstrap-dev-user":
            await bootstrap_dev_user()
        else:
            await diagnose(apply=args.apply, stale_minutes=max(args.stale_minutes, 1))
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main_async())
