from pathlib import Path


def test_reddit_package_does_not_expose_engagement_automation() -> None:
    package_root = Path("app/reddit")
    forbidden = ("submit(", ".reply(", ".message(", ".upvote(", ".downvote(")

    offenders: list[str] = []
    for path in package_root.rglob("*.py"):
        text = path.read_text()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path}:{token}")

    assert offenders == []
