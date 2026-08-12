from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "tracelink_http_requests_total",
    "HTTP requests",
    ("method", "route", "status_class"),
)
HTTP_LATENCY = Histogram(
    "tracelink_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "route"),
)
CELERY_JOBS = Counter(
    "tracelink_celery_jobs_total",
    "Celery task outcomes",
    ("task", "outcome"),
)
CONNECTOR_FAILURES = Counter(
    "tracelink_connector_failures_total",
    "Connector failures",
    ("connector", "code"),
)
LLM_CALLS = Counter("tracelink_llm_calls_total", "LLM calls", ("provider", "outcome"))
EMBEDDING_BATCHES = Counter(
    "tracelink_embedding_batches_total",
    "Embedding batches",
    ("provider", "outcome"),
)
CACHE_OPERATIONS = Counter(
    "tracelink_cache_operations_total",
    "Cache operations",
    ("cache", "result"),
)
