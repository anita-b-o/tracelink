import json
import logging

from tracelink.core.logging import JsonFormatter


def test_json_formatter_includes_workflow_correlation_fields() -> None:
    record = logging.LogRecord(
        "tracelink.jobs.research",
        logging.INFO,
        __file__,
        1,
        "research task started",
        (),
        None,
    )
    record.investigation_id = "investigation-1"
    record.research_task_id = "task-1"
    record.celery_task_id = "celery-1"
    record.task_type = "WEB_SEARCH"
    record.status = "RUNNING"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["investigation_id"] == "investigation-1"
    assert payload["research_task_id"] == "task-1"
    assert payload["celery_task_id"] == "celery-1"
    assert payload["task_type"] == "WEB_SEARCH"
    assert payload["status"] == "RUNNING"
