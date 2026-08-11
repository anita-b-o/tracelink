from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TraceLink API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://tracelink:tracelink_dev@localhost:5432/tracelink"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_transport_max_retries: int = Field(default=3, ge=0)

    research_task_max_attempts: int = Field(default=3, ge=1)
    fake_research_delay_ms: int = Field(default=25, ge=0, le=60_000)
    fake_research_mode: (
        Literal["SUCCESS", "FAIL_ONCE", "ALWAYS_FAIL", "SLOW", "PIPELINE_SUCCESS"] | None
    ) = None
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

    @model_validator(mode="after")
    def validate_entity_pipeline_settings(self) -> "Settings":
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
        if (self.embedding_provider == "openai" or self.llm_provider == "openai") and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when an OpenAI provider is enabled")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
