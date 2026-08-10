from __future__ import annotations

from dataclasses import dataclass

from tracelink.domain.normalization import sha256_text
from tracelink.services.document_preprocessing import chunk_document

RETRIEVAL_CHUNKER_VERSION = "character-boundary-v1"


@dataclass(frozen=True, slots=True)
class RetrievalChunkSpec:
    index: int
    text: str
    start_offset: int
    end_offset: int
    content_hash: str


def chunk_document_for_retrieval(
    raw_text: str, *, chunk_size: int, overlap: int
) -> list[RetrievalChunkSpec]:
    """Build retrieval chunks independently from extraction configuration.

    Phase 6 intentionally reuses the stable character/offset implementation, but not
    extraction's chunk size or persisted chunk identity.
    """
    return [
        RetrievalChunkSpec(
            index=chunk.index,
            text=chunk.text,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            content_hash=sha256_text(chunk.text),
        )
        for chunk in chunk_document(raw_text, chunk_size=chunk_size, overlap=overlap)
    ]
