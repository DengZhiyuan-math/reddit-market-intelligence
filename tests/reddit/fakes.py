"""Fake Reddit/PRAW-like objects for offline collector tests."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeSubmission:
    id: str
    title: str = "Post title"
    selftext: str = "Post body"
    subreddit: str = "askswitzerland"
    name: str | None = None
    author: str | None = "author"
    score: int = 10
    upvote_ratio: float = 0.9
    num_comments: int = 2
    created_utc: int = 1_700_000_000
    permalink: str = "/r/askswitzerland/comments/post"
    url: str = "https://reddit.example/post"
    response_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name is None:
            self.name = f"t3_{self.id}"


class FakeSubreddit:
    def __init__(self, submissions: list[FakeSubmission] | Exception) -> None:
        self.submissions = submissions
        self.search_calls: list[dict[str, Any]] = []

    def search(self, query: str, *, sort: str, time_filter: str, limit: int):
        self.search_calls.append(
            {
                "query": query,
                "sort": sort,
                "time_filter": time_filter,
                "limit": limit,
            }
        )
        if isinstance(self.submissions, Exception):
            raise self.submissions
        return self.submissions[:limit]


class FakeReddit:
    def __init__(
        self,
        subreddits: dict[str | None, FakeSubreddit] | None = None,
        submissions: dict[str, Any] | None = None,
    ) -> None:
        self.subreddits = subreddits or {}
        self.submissions = submissions or {}

    def subreddit(self, name: str | None) -> FakeSubreddit:
        return self.subreddits[name]

    def submission(self, id: str) -> Any:
        submission = self.submissions[id]
        if isinstance(submission, Exception):
            raise submission
        return submission


@dataclass
class FakeComment:
    id: str
    body: str = "Comment body"
    author: str | None = "commenter"
    score: int = 3
    created_utc: int = 1_700_000_100
    parent_id: str = "t3_post"
    permalink: str = "/r/askswitzerland/comments/post/comment"
    replies: list["FakeComment"] = field(default_factory=list)
    name: str | None = None

    def __post_init__(self) -> None:
        if self.name is None:
            self.name = f"t1_{self.id}"


class FakeCommentForest:
    def __init__(self, comments: list[FakeComment]) -> None:
        self.comments = comments
        self.replace_more_limit: int | None = None

    def replace_more(self, *, limit: int) -> None:
        self.replace_more_limit = limit

    def __iter__(self):
        return iter(self.comments)


class FakeSubmissionWithComments(FakeSubmission):
    def __init__(self, *args, comments: FakeCommentForest, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.comments = comments
