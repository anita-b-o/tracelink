from tracelink.jobs.celery_app import celery_app


def test_celery_uses_json_and_tracks_started_tasks() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_track_started is True
    assert str(celery_app.conf.broker_url).startswith("redis://")
    assert str(celery_app.conf.result_backend).startswith("redis://")
