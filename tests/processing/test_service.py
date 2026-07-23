import math

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db.models import (
    ContentEmbeddingRecord,
    ContentItemRecord,
    PipelineRunRecord,
    ProjectRedditPostRecord,
    RedditPostRawRecord,
    RelevanceDecisionRecord,
)
import app.db.models  # noqa: F401
from app.processing.embeddings import EmbeddingResult
from app.processing.models import ACCEPTED, AMBIGUOUS, REJECTED
from app.processing.service import ProcessingServiceError, run_filtering
from tests.processing.test_repository import seed_project, seed_raw_comment, seed_raw_post


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> EmbeddingResult:
        lowered = text.casefold()
        if "borderline" in lowered:
            vector = [0.5, math.sqrt(0.75)]
        elif "unrelated" in lowered:
            vector = [0.0, 1.0]
        else:
            vector = [1.0, 0.0]
        return EmbeddingResult(
            vector=vector,
            model="fake-keyword-v1",
            provider="fake",
            dimensions=2,
        )


class FailingEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        raise RuntimeError("embedding unavailable")


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_run_filtering_persists_completed_run_summary_and_accepts_relevant_item() -> None:
    session = make_session()
    project, query = seed_project(session)
    seed_raw_post(session, project, query)

    summary = run_filtering(
        session,
        1,
        embedding_provider=KeywordEmbeddingProvider(),
        settings=Settings(_env_file=None),
    )

    item = session.scalar(select(ContentItemRecord))
    run = session.scalar(select(PipelineRunRecord).where(PipelineRunRecord.stage == "filtering"))
    assert summary.raw_posts_processed == 1
    assert summary.content_items_created == 1
    assert summary.accepted == 1
    assert item.final_status == ACCEPTED
    assert run.status == "completed"
    assert run.summary["accepted"] == 1


def test_run_filtering_routes_borderline_item_to_ambiguous_review() -> None:
    session = make_session()
    project, query = seed_project(session)
    raw_post = RedditPostRawRecord(
        reddit_post_id="borderline-post",
        title="Borderline tutoring topic",
        body="borderline context for Zurich school help",
        raw_json={},
    )
    session.add(raw_post)
    session.flush()
    session.add(
        ProjectRedditPostRecord(
            project_id=project.id,
            search_query_id=query.id,
            reddit_post_raw_id=raw_post.id,
        )
    )
    session.commit()

    summary = run_filtering(
        session,
        1,
        embedding_provider=KeywordEmbeddingProvider(),
        settings=Settings(_env_file=None),
    )

    item = session.scalar(select(ContentItemRecord))
    assert summary.ambiguous == 1
    assert summary.llm_review_required == 1
    assert item.final_status == AMBIGUOUS
    assert item.llm_review_required is True


def test_deleted_content_is_rejected_without_embedding() -> None:
    session = make_session()
    project, query = seed_project(session)
    raw_post = RedditPostRawRecord(
        reddit_post_id="deleted-post",
        title="[deleted]",
        body=None,
        raw_json={},
    )
    session.add(raw_post)
    session.flush()
    session.add(
        ProjectRedditPostRecord(
            project_id=project.id,
            search_query_id=query.id,
            reddit_post_raw_id=raw_post.id,
        )
    )
    session.commit()

    summary = run_filtering(
        session,
        1,
        embedding_provider=KeywordEmbeddingProvider(),
        settings=Settings(_env_file=None),
    )

    item = session.scalar(select(ContentItemRecord))
    assert summary.rejected == 1
    assert summary.embedded == 0
    assert item.final_status == REJECTED
    assert session.scalars(select(ContentEmbeddingRecord)).all() == []


def test_failed_filtering_run_persists_failed_summary() -> None:
    session = make_session()
    project, query = seed_project(session)
    seed_raw_post(session, project, query)

    try:
        run_filtering(
            session,
            1,
            embedding_provider=FailingEmbeddingProvider(),
            settings=Settings(_env_file=None),
        )
    except ProcessingServiceError:
        pass

    run = session.scalar(select(PipelineRunRecord).where(PipelineRunRecord.stage == "filtering"))
    assert run.status == "failed"
    assert run.summary["errors"] == 1


def test_run_filtering_is_rerunnable_without_duplicate_content_embeddings_or_decisions() -> None:
    session = make_session()
    project, query = seed_project(session)
    seed_raw_post(session, project, query)
    seed_raw_comment(session, project, query)

    first = run_filtering(
        session,
        1,
        embedding_provider=KeywordEmbeddingProvider(),
        settings=Settings(_env_file=None),
    )
    second = run_filtering(
        session,
        1,
        embedding_provider=KeywordEmbeddingProvider(),
        settings=Settings(_env_file=None),
    )

    assert first.content_items_created == 2
    assert second.content_items_updated == 2
    assert len(session.scalars(select(ContentItemRecord)).all()) == 2
    assert len(session.scalars(select(ContentEmbeddingRecord)).all()) == 2
    assert len(session.scalars(select(RelevanceDecisionRecord)).all()) == 2
    assert all(item.source_table for item in session.scalars(select(ContentItemRecord)).all())
