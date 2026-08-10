from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

from tracelink.core.config import Settings, get_settings

EMBEDDING_DIMENSIONS = 1536


class EmbeddingProviderError(RuntimeError):
    pass


class TransientEmbeddingProviderError(EmbeddingProviderError):
    pass


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbeddingProvider:
    provider_name = "fake"
    model_name = "feature-hash-v1"
    dimensions = EMBEDDING_DIMENSIONS

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[index] += -1.0 if digest[4] & 1 else 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            if norm:
                vector = [value / norm for value in vector]
            vectors.append(vector)
        return vectors


class OpenAIEmbeddingProvider:
    provider_name = "openai"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise EmbeddingProviderError("OpenAI embedding provider is disabled")
        self.model_name = settings.embedding_model
        self._api_key = settings.openai_api_key.get_secret_value()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model_name,
                        "input": texts,
                        "dimensions": self.dimensions,
                        "encoding_format": "float",
                    },
                )
                response.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransientEmbeddingProviderError("embedding provider unavailable") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 or exc.response.status_code >= 500:
                raise TransientEmbeddingProviderError("embedding provider unavailable") from exc
            raise EmbeddingProviderError("embedding provider rejected the request") from exc
        data = response.json().get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingProviderError("embedding provider returned an invalid batch")
        ordered = sorted(data, key=lambda item: item.get("index", -1))
        vectors = [item.get("embedding") for item in ordered]
        if any(
            not isinstance(vector, list) or len(vector) != self.dimensions for vector in vectors
        ):
            raise EmbeddingProviderError("embedding provider returned an invalid dimension")
        return vectors


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    configured = settings or get_settings()
    if configured.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(configured)
    return FakeEmbeddingProvider()
