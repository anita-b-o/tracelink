from datetime import UTC, datetime

import pytest

from tracelink.domain.enums import (
    InvestigationStatus,
    ResearchTaskStatus,
    ResearchTaskType,
)
from tracelink.domain.models import Investigation, ResearchTask
from tracelink.domain.workflow import (
    INVESTIGATION_TRANSITIONS,
    RESEARCH_TASK_TRANSITIONS,
    aggregate_investigation_status,
    calculate_progress,
    transition_investigation,
    transition_research_task,
)
from tracelink.services.errors import DomainInvalidTransitionError


def investigation(status: InvestigationStatus) -> Investigation:
    return Investigation(title="Case", original_query="Query", status=status)


def research_task(status: ResearchTaskStatus, *, attempts: int = 0) -> ResearchTask:
    return ResearchTask(
        type=ResearchTaskType.WEB_SEARCH,
        status=status,
        query="Query",
        attempts=attempts,
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in INVESTIGATION_TRANSITIONS.items()
        for target in targets
        if source not in {InvestigationStatus.FAILED, InvestigationStatus.PARTIAL}
    ],
)
def test_all_standard_investigation_transitions(
    source: InvestigationStatus, target: InvestigationStatus
) -> None:
    item = investigation(source)
    transition_investigation(item, target)
    assert item.status is target


@pytest.mark.parametrize("source", [InvestigationStatus.FAILED, InvestigationStatus.PARTIAL])
def test_investigation_restart_requires_explicit_retry(source: InvestigationStatus) -> None:
    item = investigation(source)
    with pytest.raises(DomainInvalidTransitionError, match="explicit retry"):
        transition_investigation(item, InvestigationStatus.PENDING)
    transition_investigation(item, InvestigationStatus.PENDING, explicit_retry=True)
    assert item.status is InvestigationStatus.PENDING


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source in InvestigationStatus
        for target in InvestigationStatus
        if target not in INVESTIGATION_TRANSITIONS[source]
    ],
)
def test_invalid_investigation_transitions_are_rejected(
    source: InvestigationStatus, target: InvestigationStatus
) -> None:
    with pytest.raises(DomainInvalidTransitionError):
        transition_investigation(investigation(source), target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in RESEARCH_TASK_TRANSITIONS.items()
        for target in targets
        if source is not ResearchTaskStatus.FAILED
    ],
)
def test_all_standard_research_task_transitions(
    source: ResearchTaskStatus, target: ResearchTaskStatus
) -> None:
    item = research_task(source)
    transition_research_task(item, target)
    assert item.status is target


def test_research_task_timestamps_attempts_and_retry() -> None:
    item = research_task(ResearchTaskStatus.PENDING)
    first_started = datetime(2026, 8, 10, 10, tzinfo=UTC)
    failed_at = datetime(2026, 8, 10, 11, tzinfo=UTC)
    transition_research_task(
        item, ResearchTaskStatus.RUNNING, celery_task_id="job-1", now=first_started
    )
    transition_research_task(item, ResearchTaskStatus.FAILED, now=failed_at)
    item.last_error_code = "FAILED"

    transition_research_task(item, ResearchTaskStatus.PENDING, explicit_retry=True)
    transition_research_task(
        item, ResearchTaskStatus.RUNNING, celery_task_id="job-2", now=failed_at
    )

    assert item.attempts == 2
    assert item.started_at == first_started
    assert item.completed_at is None
    assert item.active_celery_task_id == "job-2"
    assert item.last_error_code == "FAILED"


def test_research_task_retry_requires_explicit_operation() -> None:
    item = research_task(ResearchTaskStatus.FAILED)
    with pytest.raises(DomainInvalidTransitionError, match="explicit"):
        transition_research_task(item, ResearchTaskStatus.PENDING)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source in ResearchTaskStatus
        for target in ResearchTaskStatus
        if target not in RESEARCH_TASK_TRANSITIONS[source]
    ],
)
def test_invalid_research_task_transitions_are_rejected(
    source: ResearchTaskStatus, target: ResearchTaskStatus
) -> None:
    with pytest.raises(DomainInvalidTransitionError):
        transition_research_task(research_task(source), target)


def test_progress_counts_terminal_tasks_and_uses_zero_for_empty_plan() -> None:
    tasks = [
        research_task(ResearchTaskStatus.PENDING),
        research_task(ResearchTaskStatus.RUNNING, attempts=1),
        research_task(ResearchTaskStatus.COMPLETED, attempts=1),
        research_task(ResearchTaskStatus.FAILED, attempts=1),
    ]
    progress = calculate_progress(tasks)
    assert progress.total == 4
    assert progress.pending == progress.running == progress.completed == progress.failed == 1
    assert progress.cancelled == 0
    assert progress.percent == 50
    assert calculate_progress([]).percent == 0


@pytest.mark.parametrize(
    ("task_statuses", "attempts", "expected"),
    [
        ([ResearchTaskStatus.PENDING] * 2, 0, InvestigationStatus.PENDING),
        ([ResearchTaskStatus.PENDING] * 2, 1, InvestigationStatus.RUNNING),
        (
            [ResearchTaskStatus.COMPLETED, ResearchTaskStatus.PENDING],
            1,
            InvestigationStatus.RUNNING,
        ),
        ([ResearchTaskStatus.COMPLETED] * 2, 1, InvestigationStatus.COMPLETED),
        ([ResearchTaskStatus.FAILED] * 2, 1, InvestigationStatus.FAILED),
        (
            [ResearchTaskStatus.COMPLETED, ResearchTaskStatus.FAILED],
            1,
            InvestigationStatus.PARTIAL,
        ),
    ],
)
def test_aggregate_investigation_policy(
    task_statuses: list[ResearchTaskStatus],
    attempts: int,
    expected: InvestigationStatus,
) -> None:
    tasks = [research_task(status, attempts=attempts) for status in task_statuses]
    assert (
        aggregate_investigation_status(investigation(InvestigationStatus.RUNNING), tasks)
        is expected
    )


def test_cancelled_investigation_is_never_overwritten() -> None:
    tasks = [research_task(ResearchTaskStatus.COMPLETED, attempts=1)]
    assert (
        aggregate_investigation_status(investigation(InvestigationStatus.CANCELLED), tasks)
        is InvestigationStatus.CANCELLED
    )
