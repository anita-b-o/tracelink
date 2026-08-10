from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, model_validator
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
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
