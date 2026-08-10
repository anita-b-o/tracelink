from pydantic import BaseModel, Field


class UrlIngestionCreate(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
