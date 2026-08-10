from __future__ import annotations

import re

from tracelink.domain.entity_extraction import ExtractedEntityCandidate
from tracelink.domain.enums import EntityType
from tracelink.domain.normalization import normalize_domain

_DOMAIN = re.compile(
    r"(?<![@\w-])(?:[\w](?:[\w-]{0,61}[\w])?\.)+[\w](?:[\w-]{0,61}[\w])?\.?(?![\w-])",
    re.UNICODE,
)
_COMPANY = re.compile(
    r"\b(?:[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&'-]*[ \t]+){0,6}"
    r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&'-]*[ \t]+"
    r"(?:S\.?[ \t]*A\.?|Sociedad[ \t]+An[oó]nima|S\.?[ \t]*R\.?[ \t]*L\.?|"
    r"SAS|Inc\.?|Corp\.?|LLC|Ltd\.?)\b"
)
_ORGANIZATION = re.compile(
    r"\b(?:Fundaci[oó]n|Asociaci[oó]n|Universidad|Instituto|Foundation|Association|University)"
    r"(?:[ \t]+(?:[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ&'-]*|de|del|of|the)){1,8}\b"
)
_PERSON = re.compile(
    r"\b(?:Sr\.?|Sra\.?|Dr\.?|Dra\.?|Mr\.?|Ms\.?|Professor|Prof\.?)\s+"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ'-]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ'-]+){1,3})\b"
)
_ADDRESS = re.compile(
    r"\b(?:Calle|Avenida|Av\.?|Boulevard|Blvd\.?|Street|St\.?|Road|Rd\.?)\s+"
    r"[A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ.' -]{1,80}?\s+\d{1,6}[A-Za-z]?\b"
    r"|\b\d{1,6}\s+[A-Z][A-Za-z.' -]{1,60}\s+(?:Street|St\.?|Road|Rd\.?|Avenue|Ave\.?)\b"
)


def _candidate(
    entity_type: EntityType,
    text: str,
    start: int,
    end: int,
    confidence: float,
    signal: str,
) -> ExtractedEntityCandidate:
    surface = text[start:end].strip()
    leading = len(text[start:end]) - len(text[start:end].lstrip())
    trailing = len(text[start:end]) - len(text[start:end].rstrip())
    return ExtractedEntityCandidate(
        type=entity_type,
        surface_form=surface,
        canonical_name_candidate=surface,
        confidence=confidence,
        start_offset=start + leading,
        end_offset=end - trailing,
        reasoning_signals=[signal],
    )


def extract_deterministic(
    text: str, allowed_types: frozenset[EntityType]
) -> list[ExtractedEntityCandidate]:
    candidates: list[ExtractedEntityCandidate] = []
    if EntityType.DOMAIN in allowed_types:
        for match in _DOMAIN.finditer(text):
            try:
                normalized = normalize_domain(match.group()).canonical
            except ValueError:
                continue
            candidates.append(
                ExtractedEntityCandidate(
                    type=EntityType.DOMAIN,
                    surface_form=match.group(),
                    canonical_name_candidate=normalized,
                    confidence=0.98,
                    start_offset=match.start(),
                    end_offset=match.end(),
                    reasoning_signals=["valid_idna_domain"],
                )
            )
    patterns = (
        (EntityType.COMPANY, _COMPANY, 0.91, "legal_suffix"),
        (EntityType.ORGANIZATION, _ORGANIZATION, 0.88, "organization_designator"),
        (EntityType.PERSON, _PERSON, 0.86, "person_honorific"),
        (EntityType.ADDRESS, _ADDRESS, 0.84, "conservative_address_pattern"),
    )
    for entity_type, pattern, confidence, signal in patterns:
        if entity_type not in allowed_types:
            continue
        for match in pattern.finditer(text):
            start, end = match.span(1) if entity_type is EntityType.PERSON else match.span()
            candidates.append(_candidate(entity_type, text, start, end, confidence, signal))
    return candidates
