import pytest

from tracelink.domain.normalization import clean_text, normalize_name, sha256_text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  ACME   Holdings\nLtd.  ", "acme holdings ltd."),
        ("ＡＣＭＥ", "acme"),
        ("Straße", "strasse"),
        ("Éxito", "éxito"),
    ],
)
def test_normalize_name_is_deterministic(value: str, expected: str) -> None:
    assert normalize_name(value) == expected


def test_clean_text_preserves_case_and_accents() -> None:
    assert clean_text("  María\tPÉREZ ") == "María PÉREZ"


def test_sha256_text_is_stable() -> None:
    assert sha256_text("TraceLink") == sha256_text("TraceLink")
    assert len(sha256_text("TraceLink")) == 64
