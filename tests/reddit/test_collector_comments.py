from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ProjectRedditCommentRecord,
    ProjectRedditPostRecord,
    RedditCommentRawRecord,
    RedditPostRawRecord,
)
import app.db.models  # noqa: F401
from app.reddit.collector import RedditCollector
from app.reddit.models import RedditCommentSnapshot
from app.reddit.repository import RedditCollectionRepository
from tests.reddit.fakes import (
    FakeComment,
    FakeCommentForest,
    FakeReddit,
    FakeSubmission,
    FakeSubmissionWithComments,
)
from tests.reddit.test_collector_posts import seed_project_with_query


class PermanentCommentError(RuntimeError):
    pass


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_project_post(session: Session) -> tuple[RedditCollectionRepository, ProjectRedditPostRecord]:
    project, query = seed_project_with_query(session)
    repository = RedditCollectionRepository(session)
    raw_post, _ = repository.upsert_raw_post(
        RedditCommentTestPost.to_post_snapshot(FakeSubmission(id="post1"))
    )
    project_post, _ = repository.link_project_post(
        project_db_id=project.id,
        run_id=None,
        search_query=query,
        request_id=None,
        raw_post=raw_post,
    )
    session.commit()
    return repository, project_post


class RedditCommentTestPost:
    @staticmethod
    def to_post_snapshot(submission: FakeSubmission):
        from app.reddit.models import RedditPostSnapshot

        return RedditPostSnapshot.from_submission(submission)


def test_repository_upserts_raw_comments_and_links_project_provenance() -> None:
    session = make_session()
    repository, project_post = seed_project_post(session)
    raw_post = repository.get_raw_post(project_post.reddit_post_raw_id)
    snapshot = RedditCommentSnapshot.from_comment(
        FakeComment(id="comment1", parent_id=f"t3_{raw_post.reddit_post_id}"),
        reddit_post_id=raw_post.reddit_post_id,
        depth=0,
    )

    raw_comment, inserted = repository.upsert_raw_comment(snapshot)
    same_comment, inserted_again = repository.upsert_raw_comment(snapshot)
    link, linked = repository.link_project_comment(
        project_db_id=project_post.project_id,
        run_id=None,
        search_query_id=project_post.search_query_id,
        request_id=None,
        raw_comment=raw_comment,
    )
    same_link, linked_again = repository.link_project_comment(
        project_db_id=project_post.project_id,
        run_id=None,
        search_query_id=project_post.search_query_id,
        request_id=None,
        raw_comment=raw_comment,
    )

    assert inserted is True
    assert inserted_again is False
    assert raw_comment.id == same_comment.id
    assert linked is True
    assert linked_again is False
    assert link.id == same_link.id
    assert session.scalars(select(RedditCommentRawRecord)).all() == [raw_comment]
    assert session.scalars(select(ProjectRedditCommentRecord)).all() == [link]


def test_collect_top_level_comments_uses_replace_more_limit_zero_and_skips_replies() -> None:
    session = make_session()
    repository, _project_post = seed_project_post(session)
    nested_reply = FakeComment(id="nested", parent_id="t1_comment1")
    top_level = FakeComment(id="comment1", replies=[nested_reply])
    comment_forest = FakeCommentForest([top_level])
    submission = FakeSubmissionWithComments(id="post1", comments=comment_forest)
    collector = RedditCollector(
        FakeReddit(submissions={"post1": submission}),
        repository,
        Settings(_env_file=None),
    )

    summary = collector.collect_top_level_comments(project_id=1, max_comments_per_post=10)
    session.commit()

    stored_comments = session.scalars(select(RedditCommentRawRecord)).all()
    assert comment_forest.replace_more_limit == 0
    assert summary.stored_comments == 1
    assert [comment.reddit_comment_id for comment in stored_comments] == ["comment1"]
    assert all(comment.depth == 0 for comment in stored_comments)
    assert "nested" not in {comment.reddit_comment_id for comment in stored_comments}


def test_collect_top_level_comments_counts_duplicate_comments() -> None:
    session = make_session()
    repository, _project_post = seed_project_post(session)
    duplicate = FakeComment(id="comment1")
    submission = FakeSubmissionWithComments(
        id="post1",
        comments=FakeCommentForest([duplicate, duplicate]),
    )
    collector = RedditCollector(
        FakeReddit(submissions={"post1": submission}),
        repository,
        Settings(_env_file=None),
    )

    summary = collector.collect_top_level_comments(project_id=1, max_comments_per_post=10)

    assert summary.stored_comments == 1
    assert summary.duplicate_comments_skipped == 1


def test_collect_top_level_comments_records_failures_without_deleting_posts() -> None:
    session = make_session()
    repository, _project_post = seed_project_post(session)
    collector = RedditCollector(
        FakeReddit(submissions={"post1": PermanentCommentError("bad comments")}),
        repository,
        Settings(_env_file=None),
    )

    summary = collector.collect_top_level_comments(project_id=1, max_comments_per_post=10)

    assert summary.request_failures == 1
    assert summary.permanent_failures == 1
    assert session.scalar(select(RedditPostRawRecord)) is not None
    assert session.scalars(select(RedditCommentRawRecord)).all() == []
