from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_ALLOWED_HOSTS = "localhost,127.0.0.1,backend,testserver,test"
DEPLOYED_APP_ENVS = frozenset({"demo", "staging", "production"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TraceLink API"
    app_env: Literal["development", "test", "demo", "staging", "production"] = Field(
        default="development", validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT")
    )
    log_level: str = "INFO"
    cors_allowed_origins: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS", "CORS_ORIGINS"),
    )
    allowed_hosts: str = DEVELOPMENT_ALLOWED_HOSTS
    api_docs_enabled: bool = True
    max_request_body_bytes: int = Field(default=262_144, ge=1024, le=10_000_000)

    database_url: str = "postgresql+psycopg://tracelink:tracelink_dev@localhost:5432/tracelink"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86_400)
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=30_000, ge=1000, le=600_000)

    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    redis_socket_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    redis_health_check_interval_seconds: int = Field(default=30, ge=1, le=300)
    redis_retry_count: int = Field(default=3, ge=0, le=10)

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_transport_max_retries: int = Field(default=3, ge=0)
    celery_visibility_timeout_seconds: int = Field(default=900, ge=60, le=86_400)
    celery_worker_concurrency: int = Field(default=2, ge=1, le=32)
    celery_worker_max_tasks_per_child: int = Field(default=100, ge=1, le=10_000)
    celery_task_soft_time_limit_seconds: int = Field(default=300, ge=30, le=3600)
    celery_task_time_limit_seconds: int = Field(default=330, ge=31, le=3660)

    auth_jwt_secret: SecretStr = SecretStr("development-jwt-secret-change-me-32-bytes")
    auth_token_pepper: SecretStr = SecretStr("development-token-pepper-change-me-32")
    auth_issuer: str = "tracelink"
    auth_audience: str = "tracelink-web"
    access_token_minutes: int = Field(default=10, ge=1, le=60)
    refresh_token_days: int = Field(default=30, ge=1, le=365)
    cookie_secure: bool | None = None
    registration_enabled: bool | None = None
    dev_bootstrap_email: str = "dev@tracelink.local"
    dev_bootstrap_password: SecretStr = SecretStr("tracelink-development")

    rate_limit_login_count: int = Field(default=5, ge=1, le=1000)
    rate_limit_register_count: int = Field(default=3, ge=1, le=1000)
    rate_limit_refresh_count: int = Field(default=30, ge=1, le=1000)
    rate_limit_ask_count: int = Field(default=20, ge=1, le=1000)
    rate_limit_reports_count: int = Field(default=6, ge=1, le=1000)
    rate_limit_url_ingestion_count: int = Field(default=20, ge=1, le=1000)
    rate_limit_start_count: int = Field(default=10, ge=1, le=1000)

    metrics_bearer_token: SecretStr | None = None
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0, le=1)

    outbox_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=60)
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_max_attempts: int = Field(default=10, ge=1, le=100)
    outbox_lease_seconds: int = Field(default=60, ge=10, le=3600)
    outbox_retention_days: int = Field(default=7, ge=1, le=365)

    research_task_max_attempts: int = Field(default=3, ge=1)
    fake_research_delay_ms: int = Field(default=25, ge=0, le=60_000)
    fake_research_mode: (
        Literal["SUCCESS", "FAIL_ONCE", "ALWAYS_FAIL", "SLOW", "PIPELINE_SUCCESS"] | None
    ) = None
    demo_mode: bool = False
    e2e_seed_enabled: bool = False
    test_auth_bypass: bool = False
    research_http_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    research_http_max_response_bytes: int = Field(default=5_000_000, ge=1, le=50_000_000)
    research_http_max_redirects: int = Field(default=5, ge=0, le=20)
    research_http_user_agent: str = Field(
        default="TraceLink/0.1 ResearchConnector", min_length=1, max_length=300
    )
    research_web_search_max_results: int = Field(default=10, ge=1, le=100)
    research_cache_ttl_seconds: int = Field(default=3600, ge=1, le=604_800)
    research_connector_requests_per_second: int = Field(default=2, ge=1, le=100)

    entity_extraction_chunk_size: int = Field(default=4000, ge=500, le=100_000)
    entity_extraction_chunk_overlap: int = Field(default=300, ge=0, le=10_000)
    entity_resolution_auto_match_threshold: float = Field(default=0.90, ge=0, le=1)
    entity_resolution_possible_match_threshold: float = Field(default=0.65, ge=0, le=1)
    relationship_auto_accept_threshold: float = Field(default=0.90, ge=0, le=1)
    relationship_possible_threshold: float = Field(default=0.65, ge=0, le=1)
    relationship_max_candidates_per_document: int = Field(default=100, ge=1, le=1000)

    rag_chunk_size: int = Field(default=1600, ge=500, le=100_000)
    rag_chunk_overlap: int = Field(default=200, ge=0, le=10_000)
    rag_top_k: int = Field(default=10, ge=1, le=50)
    rag_semantic_weight: float = Field(default=0.70, ge=0, le=1)
    rag_lexical_weight: float = Field(default=0.30, ge=0, le=1)
    rag_min_retrieval_score: float = Field(default=0.20, ge=0, le=1)
    rag_min_evidence_count: int = Field(default=1, ge=0, le=100)
    rag_max_context_chars: int = Field(default=24_000, ge=1000, le=1_000_000)
    embedding_batch_size: int = Field(default=32, ge=1, le=2048)
    embedding_provider: Literal["fake", "openai"] = "fake"
    embedding_model: str = "text-embedding-3-small"
    llm_provider: Literal["fake", "openai"] = "fake"
    llm_model: str = "gpt-5.6-luna"
    openai_api_key: SecretStr | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_driver(cls, value: object) -> object:
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return value.replace("postgres://", "postgresql+psycopg://", 1)
            if value.startswith("postgresql://"):
                return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.demo_mode != (self.app_env == "demo"):
            raise ValueError("DEMO_MODE=true is required only when APP_ENV=demo")
        if self.entity_extraction_chunk_overlap >= self.entity_extraction_chunk_size:
            raise ValueError("entity extraction overlap must be smaller than chunk size")
        if (
            self.entity_resolution_possible_match_threshold
            >= self.entity_resolution_auto_match_threshold
        ):
            raise ValueError("possible match threshold must be lower than auto match threshold")
        if self.relationship_possible_threshold >= self.relationship_auto_accept_threshold:
            raise ValueError(
                "relationship possible threshold must be lower than auto accept threshold"
            )
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG chunk overlap must be smaller than chunk size")
        if abs(self.rag_semantic_weight + self.rag_lexical_weight - 1.0) > 1e-9:
            raise ValueError("RAG semantic and lexical weights must sum to 1")
        if self.celery_task_soft_time_limit_seconds >= self.celery_task_time_limit_seconds:
            raise ValueError("Celery soft time limit must be lower than hard time limit")
        if self.app_env == "demo" and self.outbox_batch_size != 1:
            raise ValueError("demo outbox processing requires OUTBOX_BATCH_SIZE=1")
        if (
            self.app_env == "demo"
            and self.outbox_lease_seconds <= self.celery_task_time_limit_seconds
        ):
            raise ValueError("demo outbox lease must exceed the task hard time limit")
        if (self.embedding_provider == "openai" or self.llm_provider == "openai") and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when an OpenAI provider is enabled")
        if "*" in self.cors_origin_list:
            raise ValueError("wildcard CORS origins are not allowed")
        if not self.allowed_host_list or "*" in self.allowed_host_list:
            raise ValueError("ALLOWED_HOSTS must contain explicit hostnames")
        for origin in self.cors_origin_list:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("CORS_ALLOWED_ORIGINS must contain exact HTTP(S) origins")
        if self.app_env in DEPLOYED_APP_ENVS:
            if self.allowed_hosts == DEVELOPMENT_ALLOWED_HOSTS:
                raise ValueError("ALLOWED_HOSTS must be explicit in deployed environments")
            if "127.0.0.1" not in self.allowed_host_list:
                raise ValueError("ALLOWED_HOSTS must include 127.0.0.1 for container healthchecks")
            if self.registration_enabled is None:
                raise ValueError("REGISTRATION_ENABLED must be explicit in deployed environments")
            jwt_secret = self.auth_jwt_secret.get_secret_value()
            pepper = self.auth_token_pepper.get_secret_value()
            if len(jwt_secret.encode()) < 32 or len(pepper.encode()) < 32 or jwt_secret == pepper:
                raise ValueError("production auth secrets must be distinct and at least 32 bytes")
            if self.cookie_secure is False:
                raise ValueError("secure cookies cannot be disabled in deployed environments")
            if self.e2e_seed_enabled or self.fake_research_mode is not None:
                raise ValueError("E2E/fake research modes are forbidden in deployed environments")
            if self.embedding_provider == "fake" or self.llm_provider == "fake":
                raise ValueError("fake AI providers are forbidden in deployed environments")
            if any(not origin.startswith("https://") for origin in self.cors_origin_list):
                raise ValueError("deployed CORS origins must use HTTPS")
        if self.test_auth_bypass and self.app_env != "test":
            raise ValueError("TEST_AUTH_BYPASS is only allowed in test")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed_host_list(self) -> list[str]:
        hosts = [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
        if self.app_env in DEPLOYED_APP_ENVS and "127.0.0.1" not in hosts:
            hosts.append("127.0.0.1")
        return hosts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def secure_cookies(self) -> bool:
        return (
            self.cookie_secure
            if self.cookie_secure is not None
            else self.app_env in DEPLOYED_APP_ENVS
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def registration_is_enabled(self) -> bool:
        return (
            self.registration_enabled
            if self.registration_enabled is not None
            else self.app_env in {"development", "test"}
        )

    @property
    def environment(self) -> str:
        """Compatibility bridge for phase 1-7 code."""
        return self.app_env


@lru_cache
def get_settings() -> Settings:
    return Settings()
