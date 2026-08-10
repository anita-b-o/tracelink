import hashlib
import unicodedata


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def clean_text(value: str) -> str:
    return collapse_whitespace(unicodedata.normalize("NFKC", value).strip())


def normalize_name(value: str) -> str:
    return clean_text(value).casefold()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
