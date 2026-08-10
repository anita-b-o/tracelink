import json
import logging
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    """Small JSON formatter that avoids serializing arbitrary record attributes."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for field in (
            "investigation_id",
            "research_task_id",
            "celery_task_id",
            "task_type",
            "status",
            "connector",
            "url_host",
            "status_code",
            "duration_ms",
            "cache_hit",
            "retry_count",
            "document_id",
            "entity_mention_id",
            "entity_id",
            "entity_type",
            "resolution_decision",
            "resolution_score",
            "extraction_method",
            "mention_count",
            "retrieval_chunk_id",
            "retrieval_chunk_count",
            "embedding_generated_count",
            "embedding_provider",
            "embedding_model",
            "retrieval_top_k",
            "semantic_score",
            "lexical_score",
            "combined_score",
            "result_count",
            "report_id",
            "llm_provider",
            "llm_model",
            "abstained",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
