import hashlib
import re
import unicodedata
from dataclasses import dataclass

from tracelink.domain.enums import EntityType


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def clean_text(value: str) -> str:
    return collapse_whitespace(unicodedata.normalize("NFKC", value).strip())


def normalize_name(value: str) -> str:
    return clean_text(value).casefold()


@dataclass(frozen=True, slots=True)
class NormalizedEntityName:
    canonical: str
    normalized: str
    comparison_key: str


_PUNCTUATION_SPACING = re.compile(r"\s*([,;:])\s*")
_LEGAL_PUNCTUATION = re.compile(r"[.,]")
_LEGAL_SUFFIXES = re.compile(
    r"(?:\s+(?:s\s*a|sociedad\s+an[oó]nima|s\s*r\s*l|sociedad\s+de\s+"
    r"responsabilidad\s+limitada|ltda|limitada|inc(?:orporated)?|corp(?:oration)?|"
    r"llc|ltd|plc|gmbh|ag|sas|s\s+a\s+s))+$",
    re.IGNORECASE,
)
_ADDRESS_ABBREVIATIONS = {
    "avenida": "av",
    "av.": "av",
    "street": "st",
    "st.": "st",
    "road": "rd",
    "rd.": "rd",
    "boulevard": "blvd",
    "blvd.": "blvd",
}


def _canonical_text(value: str) -> str:
    return _PUNCTUATION_SPACING.sub(r"\1 ", clean_text(value)).strip()


def normalize_person(value: str) -> NormalizedEntityName:
    canonical = _canonical_text(value)
    normalized = canonical.casefold()
    comparison = re.sub(r"\s+", " ", normalized.replace("’", "'")).strip(" ,;")
    return NormalizedEntityName(canonical, normalized, comparison)


def _normalize_legal_entity(value: str) -> NormalizedEntityName:
    canonical = _canonical_text(value)
    normalized = canonical.casefold()
    punctuation_free = collapse_whitespace(_LEGAL_PUNCTUATION.sub(" ", normalized))
    comparison = collapse_whitespace(_LEGAL_SUFFIXES.sub("", punctuation_free)).strip(" -")
    return NormalizedEntityName(canonical, normalized, comparison or punctuation_free)


def normalize_company(value: str) -> NormalizedEntityName:
    return _normalize_legal_entity(value)


def normalize_organization(value: str) -> NormalizedEntityName:
    return _normalize_legal_entity(value)


def normalize_domain(value: str) -> NormalizedEntityName:
    candidate = clean_text(value).rstrip(".").lower()
    if not candidate or any(character in candidate for character in "/:@"):
        raise ValueError("domain must be a bare hostname")
    try:
        ascii_domain = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("domain is not valid IDNA") from exc
    if len(ascii_domain) > 253:
        raise ValueError("domain is too long")
    labels = ascii_domain.split(".")
    if (
        len(labels) < 2
        or len(labels[-1]) < 2
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or re.fullmatch(r"[a-z0-9-]+", label) is None
            for label in labels
        )
    ):
        raise ValueError("domain is not valid")
    return NormalizedEntityName(ascii_domain, ascii_domain, ascii_domain)


def normalize_address(value: str) -> NormalizedEntityName:
    canonical = _canonical_text(value)
    normalized = canonical.casefold()
    tokens = [_ADDRESS_ABBREVIATIONS.get(token, token.rstrip(".")) for token in normalized.split()]
    comparison = " ".join(tokens).replace(" ,", ",").strip(" ,;")
    return NormalizedEntityName(canonical, normalized, comparison)


def normalize_entity_name(entity_type: EntityType, value: str) -> NormalizedEntityName:
    if entity_type is EntityType.PERSON:
        return normalize_person(value)
    if entity_type is EntityType.COMPANY:
        return normalize_company(value)
    if entity_type is EntityType.ORGANIZATION:
        return normalize_organization(value)
    if entity_type is EntityType.DOMAIN:
        return normalize_domain(value)
    if entity_type is EntityType.ADDRESS:
        return normalize_address(value)
    canonical = _canonical_text(value)
    normalized = canonical.casefold()
    return NormalizedEntityName(canonical, normalized, normalized)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
