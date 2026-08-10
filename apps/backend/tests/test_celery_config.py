from collections.abc import Coroutine
from typing import cast
from uuid import uuid4

import pytest
from celery.exceptions import Retry

from tracelink.domain.relationship_extraction import (
    RelationshipProviderOutputError,
    TransientRelationshipExtractionProviderError,
)
from tracelink.jobs.celery_app import celery_app
from tracelink.jobs.relationships import process_document_relationships


def test_celery_uses_json_and_tracks_started_tasks() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_track_started is True
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.worker_hijack_root_logger is False
    assert str(celery_app.conf.broker_url).startswith("redis://")
    assert str(celery_app.conf.result_backend).startswith("redis://")


def test_relationship_task_retries_only_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def transient(_: object) -> None:
        cast(Coroutine[object, object, object], _).close()
        raise TransientRelationshipExtractionProviderError("temporary")

    monkeypatch.setattr("tracelink.jobs.relationships.async_worker_runtime.run", transient)
    with pytest.raises(Retry):
        process_document_relationships.apply(args=[str(uuid4()), str(uuid4())], throw=True).get()

    def permanent(_: object) -> None:
        cast(Coroutine[object, object, object], _).close()
        raise RelationshipProviderOutputError("invalid")

    monkeypatch.setattr("tracelink.jobs.relationships.async_worker_runtime.run", permanent)
    with pytest.raises(RelationshipProviderOutputError):
        process_document_relationships.apply(args=[str(uuid4()), str(uuid4())], throw=True).get()
