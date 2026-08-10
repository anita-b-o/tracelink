from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from tracelink.domain.enums import InvestigationStatus, ResearchTaskStatus
from tracelink.domain.models import Investigation, ResearchTask
from tracelink.services.errors import DomainInvalidTransitionError

INVESTIGATION_TRANSITIONS: dict[InvestigationStatus, frozenset[InvestigationStatus]] = {
    InvestigationStatus.DRAFT: frozenset(
        {InvestigationStatus.PENDING, InvestigationStatus.CANCELLED}
    ),
    InvestigationStatus.PENDING: frozenset(
        {
            InvestigationStatus.RUNNING,
            InvestigationStatus.FAILED,
            InvestigationStatus.CANCELLED,
        }
    ),
    InvestigationStatus.RUNNING: frozenset(
        {
            InvestigationStatus.COMPLETED,
            InvestigationStatus.PARTIAL,
            InvestigationStatus.FAILED,
            InvestigationStatus.CANCELLED,
        }
    ),
    InvestigationStatus.FAILED: frozenset({InvestigationStatus.PENDING}),
    InvestigationStatus.PARTIAL: frozenset({InvestigationStatus.PENDING}),
    InvestigationStatus.COMPLETED: frozenset(),
    InvestigationStatus.CANCELLED: frozenset(),
}

RESEARCH_TASK_TRANSITIONS: dict[ResearchTaskStatus, frozenset[ResearchTaskStatus]] = {
    ResearchTaskStatus.PENDING: frozenset(
        {ResearchTaskStatus.RUNNING, ResearchTaskStatus.CANCELLED}
    ),
    ResearchTaskStatus.RUNNING: frozenset(
        {
            ResearchTaskStatus.COMPLETED,
            ResearchTaskStatus.FAILED,
            ResearchTaskStatus.CANCELLED,
        }
    ),
    ResearchTaskStatus.FAILED: frozenset({ResearchTaskStatus.PENDING}),
    ResearchTaskStatus.COMPLETED: frozenset(),
    ResearchTaskStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class InvestigationProgress:
    total: int
    pending: int
    running: int
    completed: int
    failed: int
    cancelled: int
    percent: int


def calculate_progress(tasks: Iterable[ResearchTask]) -> InvestigationProgress:
    items = list(tasks)
    counts = {status: 0 for status in ResearchTaskStatus}
    for task in items:
        counts[task.status] += 1
    terminal = (
        counts[ResearchTaskStatus.COMPLETED]
        + counts[ResearchTaskStatus.FAILED]
        + counts[ResearchTaskStatus.CANCELLED]
    )
    total = len(items)
    return InvestigationProgress(
        total=total,
        pending=counts[ResearchTaskStatus.PENDING],
        running=counts[ResearchTaskStatus.RUNNING],
        completed=counts[ResearchTaskStatus.COMPLETED],
        failed=counts[ResearchTaskStatus.FAILED],
        cancelled=counts[ResearchTaskStatus.CANCELLED],
        percent=(terminal * 100 // total) if total else 0,
    )


def aggregate_investigation_status(
    investigation: Investigation, tasks: Iterable[ResearchTask]
) -> InvestigationStatus:
    if investigation.status is InvestigationStatus.CANCELLED:
        return InvestigationStatus.CANCELLED

    items = list(tasks)
    if not items:
        return investigation.status

    progress = calculate_progress(items)
    if progress.pending or progress.running:
        has_started = any(task.attempts > 0 for task in items)
        return InvestigationStatus.RUNNING if has_started else InvestigationStatus.PENDING
    if progress.completed == progress.total:
        return InvestigationStatus.COMPLETED
    if progress.completed:
        return InvestigationStatus.PARTIAL
    return InvestigationStatus.FAILED


def transition_investigation(
    investigation: Investigation,
    target: InvestigationStatus,
    *,
    explicit_retry: bool = False,
) -> None:
    source = investigation.status
    if target not in INVESTIGATION_TRANSITIONS[source]:
        raise DomainInvalidTransitionError(
            f"investigation cannot transition from {source.value} to {target.value}"
        )
    if source in {InvestigationStatus.FAILED, InvestigationStatus.PARTIAL} and not explicit_retry:
        raise DomainInvalidTransitionError(
            f"investigation transition from {source.value} requires an explicit retry"
        )
    investigation.status = target


def transition_research_task(
    research_task: ResearchTask,
    target: ResearchTaskStatus,
    *,
    explicit_retry: bool = False,
    celery_task_id: str | None = None,
    now: datetime | None = None,
) -> None:
    source = research_task.status
    if target not in RESEARCH_TASK_TRANSITIONS[source]:
        raise DomainInvalidTransitionError(
            f"research task cannot transition from {source.value} to {target.value}"
        )
    if source is ResearchTaskStatus.FAILED and not explicit_retry:
        raise DomainInvalidTransitionError("research task retry must be explicit")

    timestamp = now or datetime.now(UTC)
    research_task.status = target
    if target is ResearchTaskStatus.RUNNING:
        research_task.started_at = research_task.started_at or timestamp
        research_task.completed_at = None
        research_task.attempts += 1
        research_task.active_celery_task_id = celery_task_id
    elif target in {
        ResearchTaskStatus.COMPLETED,
        ResearchTaskStatus.FAILED,
        ResearchTaskStatus.CANCELLED,
    }:
        research_task.completed_at = timestamp
    elif target is ResearchTaskStatus.PENDING:
        research_task.completed_at = None
        research_task.result = None
        research_task.active_celery_task_id = None
