"""Phase 4 boundary tests."""

from pathlib import Path


def test_topic_planning_paths_do_not_import_reddit_or_llm_network_clients() -> None:
    combined = ""
    for file_path in Path("app/topic_planning").rglob("*.py"):
        combined += file_path.read_text()

    lowered = combined.casefold()
    for forbidden in (
        "praw",
        "asyncpraw",
        "openai",
        "responses.create",
        "chat.completions",
        "requests.",
        "httpx",
    ):
        assert forbidden not in lowered
