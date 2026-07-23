from app.processing.language_detector import (
    detect_language,
    is_allowed_language,
    normalize_language_codes,
)


def test_detects_english_tutoring_text() -> None:
    assert detect_language("Looking for a math tutor to help my child with school") == "en"


def test_detects_german_nachhilfe_text() -> None:
    assert detect_language("Suche Nachhilfe für Mathematik am Gymnasium in Zürich") == "de"


def test_empty_or_unclear_text_is_unknown() -> None:
    assert detect_language("") == "unknown"
    assert detect_language("xyz abc 123") == "unknown"


def test_unknown_language_is_allowed_by_default() -> None:
    assert is_allowed_language("unknown", ["en", "de"])


def test_empty_config_allows_any_detected_language() -> None:
    assert is_allowed_language("fr", [])


def test_normalize_language_codes_accepts_names_and_codes() -> None:
    assert normalize_language_codes(["English", "deutsch"]) == {"en", "de"}

