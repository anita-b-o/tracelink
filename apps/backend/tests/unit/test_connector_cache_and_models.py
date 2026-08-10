from uuid import uuid4

from tracelink.connectors.cache import build_cache_key
from tracelink.connectors.models import ResearchTaskResult


def test_cache_key_is_stable_and_does_not_expose_input() -> None:
    first = build_cache_key("web_search", {"query": "Sensitive Person", "limit": 10})
    second = build_cache_key("web_search", {"limit": 10, "query": "Sensitive Person"})
    assert first == second
    assert "Sensitive" not in first


def test_research_task_result_serializes_uuid_ids() -> None:
    source_id = uuid4()
    value = ResearchTaskResult(
        connector="rdap",
        status="success",
        source_ids=[source_id],
        result_count=1,
    )
    assert value.model_dump(mode="json")["source_ids"] == [str(source_id)]
