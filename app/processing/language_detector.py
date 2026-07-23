"""Deterministic language labeling for early relevance filtering."""

LANGUAGE_ALIASES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "de": "de",
    "deu": "de",
    "ger": "de",
    "german": "de",
    "deutsch": "de",
}

ENGLISH_MARKERS = {
    "the",
    "and",
    "for",
    "with",
    "looking",
    "recommend",
    "tutor",
    "math",
    "school",
    "child",
    "daughter",
    "son",
    "help",
}

GERMAN_MARKERS = {
    "der",
    "die",
    "das",
    "und",
    "für",
    "mit",
    "nachhilfe",
    "mathematik",
    "schule",
    "gymnasium",
    "matura",
    "zürich",
    "hilfe",
}


def normalize_language_codes(languages: list[str]) -> set[str]:
    """Normalize user language names into compact language codes."""

    normalized: set[str] = set()
    for language in languages:
        key = language.strip().casefold()
        if not key:
            continue
        normalized.add(LANGUAGE_ALIASES.get(key, key))
    return normalized


def detect_language(text: str) -> str:
    """Return `en`, `de`, or `unknown` using deterministic marker counts."""

    tokens = _tokens(text)
    if not tokens:
        return "unknown"
    english_score = sum(1 for token in tokens if token in ENGLISH_MARKERS)
    german_score = sum(1 for token in tokens if token in GERMAN_MARKERS)
    if german_score > english_score and german_score > 0:
        return "de"
    if english_score > german_score and english_score > 0:
        return "en"
    return "unknown"


def is_allowed_language(detected: str, configured: list[str]) -> bool:
    """Return whether a detected language should remain eligible.

    Unknown language is allowed by default to preserve the Phase 6 low-false-negative
    routing decision.
    """

    allowed = normalize_language_codes(configured)
    if not allowed or detected == "unknown":
        return True
    return detected in allowed


def _tokens(text: str) -> list[str]:
    return [token.strip(".,!?;:()[]{}\"'").casefold() for token in text.split()]

