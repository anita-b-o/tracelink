from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    index: int
    text: str
    start_offset: int
    end_offset: int
    _offset_map: tuple[int, ...]

    def to_document_offsets(self, start: int, end: int) -> tuple[int, int]:
        if start < 0 or end <= start or end > len(self.text):
            raise ValueError("candidate offsets fall outside the chunk")
        return self._offset_map[start], self._offset_map[end]


def _processing_view(raw_text: str) -> tuple[str, tuple[int, ...]]:
    characters: list[str] = []
    offsets: list[int] = []
    index = 0
    while index < len(raw_text):
        character = raw_text[index]
        offsets.append(index)
        if character == "\r":
            characters.append("\n")
            if index + 1 < len(raw_text) and raw_text[index + 1] == "\n":
                index += 2
                continue
        elif character == "\x00" or (
            unicodedata.category(character) == "Cc" and character not in "\n\t"
        ):
            characters.append(" ")
        else:
            characters.append(character)
        index += 1
    offsets.append(len(raw_text))
    return "".join(characters), tuple(offsets)


def _preferred_end(text: str, start: int, target: int) -> int:
    minimum = start + max(1, int((target - start) * 0.6))
    for marker in ("\n\n", ". ", "\n", " "):
        position = text.rfind(marker, minimum, target)
        if position >= minimum:
            return position + len(marker)
    return target


def chunk_document(raw_text: str, *, chunk_size: int, overlap: int) -> list[DocumentChunk]:
    if chunk_size < 500:
        raise ValueError("chunk_size must be at least 500 characters")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    processing_text, offsets = _processing_view(raw_text)
    if not processing_text:
        return []

    chunks: list[DocumentChunk] = []
    start = 0
    while start < len(processing_text):
        target = min(len(processing_text), start + chunk_size)
        end = (
            target
            if target == len(processing_text)
            else _preferred_end(processing_text, start, target)
        )
        chunks.append(
            DocumentChunk(
                index=len(chunks),
                text=processing_text[start:end],
                start_offset=offsets[start],
                end_offset=offsets[end],
                _offset_map=tuple(offsets[start : end + 1]),
            )
        )
        if end == len(processing_text):
            break
        next_start = max(start + 1, end - overlap)
        while (
            next_start > start
            and next_start < end
            and not processing_text[next_start - 1].isspace()
        ):
            next_start -= 1
        start = next_start if next_start > start else end
    return chunks
