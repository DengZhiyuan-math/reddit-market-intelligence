"""Synthetic offline imports through real filtering, analysis, and reports."""

import csv

import pytest
from sqlalchemy import select

from app.analysis.gateway import DeterministicSignalProvider
from app.analysis.service import run_signal_extraction
from app.config import Settings
from app.db.models import (
    ContentItemRecord,
    MarketSignalRecord,
    RedditPostRawRecord,
    ResearchProjectRecord,
)
from app.processing.service import run_filtering
from app.reddit.export_import import import_reddit_export
from app.reports.exporter import export_report_evidence
from app.reports.repository import ReportRepository
from app.reports.service import generate_market_report
from tests.processing.test_service import KeywordEmbeddingProvider
from tests.reddit.test_export_import import make_session, listing, post, write_json

QUOTE = "Can anyone recommend a math tutor in Zurich?"


def test_changed_cross_project_import_analyzes_its_own_acquired_text(tmp_path):
    session = make_session()
    session.add(
        ResearchProjectRecord(
            project_id=2,
            slug="second-import",
            topic="Zurich tutoring",
            languages=["en"],
            access_mode="personal",
        )
    )
    session.commit()
    original = post()
    original["data"]["selftext"] = QUOTE
    import_reddit_export(
        session,
        project_id=1,
        input_path=write_json(tmp_path, listing([original])),
        acquisition_method="web_json",
    )
    latest = post()
    latest["data"]["selftext"] = "We need different math tutoring for school exams in Zurich."
    import_reddit_export(
        session,
        project_id=2,
        input_path=write_json(tmp_path, listing([latest])),
        acquisition_method="dom",
        captured_at="2026-10-12T10:00:00Z",
    )
    settings = Settings(_env_file=None)
    run_filtering(session, 2, embedding_provider=KeywordEmbeddingProvider(), settings=settings)
    project = session.scalar(
        select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == 2)
    )
    item = session.scalar(
        select(ContentItemRecord).where(ContentItemRecord.project_id == project.id)
    )
    assert latest["data"]["selftext"] in item.text
    assert QUOTE not in item.text
    assert item.source_mode == "dom"
    assert session.scalar(select(RedditPostRawRecord)).body == QUOTE
    run_signal_extraction(session, 2, settings=settings)
    evidence = ReportRepository(session).list_evidence_items(project.id)[0]
    assert latest["data"]["selftext"] in evidence.quote
    assert evidence.source_mode == "dom"


def test_api_collection_after_import_uses_its_actual_post_and_comment_text(tmp_path):
    from app.reddit.service import run_reddit_collection
    from tests.reddit.fakes import (
        FakeComment,
        FakeCommentForest,
        FakeReddit,
        FakeSubmissionWithComments,
        FakeSubreddit,
    )
    from tests.reddit.test_collector_posts import (
        make_session as empty_session,
        seed_project_with_query,
    )

    session = empty_session()
    api_project, _ = seed_project_with_query(session)
    session.add(
        ResearchProjectRecord(
            project_id=2,
            slug="first-import",
            topic="Zurich tutoring",
            languages=["en"],
            access_mode="personal",
        )
    )
    session.commit()
    imported_post = post()
    imported_post["data"]["selftext"] = QUOTE
    comment = {
        "kind": "t1",
        "data": {
            "id": "c1",
            "link_id": "t3_abc",
            "parent_id": "t3_abc",
            "body": QUOTE,
            "permalink": "/r/zurich/comments/abc/title/c1/",
        },
    }
    import_reddit_export(
        session,
        project_id=2,
        input_path=write_json(tmp_path, [listing([imported_post]), listing([comment])]),
        acquisition_method="web_json",
    )
    api_body = "We need new math tutoring for school exams in Zurich."
    submission = FakeSubmissionWithComments(
        id="abc",
        selftext=api_body,
        comments=FakeCommentForest([FakeComment(id="c1", body=api_body, parent_id="t3_abc")]),
    )
    settings = Settings(
        _env_file=None,
        reddit_client_id="test",
        reddit_client_secret="test",
        reddit_user_agent="reddit-market-intel/0.1 by tests@example.com",
    )
    run_reddit_collection(
        session,
        1,
        1,
        1,
        settings=settings,
        reddit_client=FakeReddit(
            {"askswitzerland": FakeSubreddit([submission])}, {"abc": submission}
        ),
    )
    run_filtering(session, 1, embedding_provider=KeywordEmbeddingProvider(), settings=settings)
    items = session.scalars(
        select(ContentItemRecord).where(ContentItemRecord.project_id == api_project.id)
    ).all()
    assert len(items) == 2
    assert all(api_body in item.text and QUOTE not in item.text for item in items)
    assert all(item.source_mode == "reddit_api" for item in items)
    assert session.scalar(select(RedditPostRawRecord)).body == QUOTE


def test_later_api_query_in_same_project_keeps_first_acquisition_provenance(tmp_path):
    from app.reddit.service import run_reddit_collection
    from tests.reddit.fakes import FakeReddit, FakeSubmission, FakeSubreddit
    from tests.reddit.test_collector_posts import (
        make_session as empty_session,
        seed_project_with_query,
    )

    session = empty_session()
    project, _ = seed_project_with_query(session)
    source = post()
    source["data"]["selftext"] = QUOTE
    import_reddit_export(
        session,
        project_id=1,
        input_path=write_json(tmp_path, listing([source])),
        acquisition_method="web_json",
    )
    settings = Settings(
        _env_file=None,
        reddit_client_id="test",
        reddit_client_secret="test",
        reddit_user_agent="reddit-market-intel/0.1 by tests@example.com",
    )
    run_reddit_collection(
        session,
        1,
        1,
        0,
        collect_comments=False,
        settings=settings,
        reddit_client=FakeReddit(
            {
                "askswitzerland": FakeSubreddit(
                    [
                        FakeSubmission(
                            id="abc", selftext="A different math tutoring request in Zurich."
                        )
                    ]
                )
            }
        ),
    )
    run_filtering(session, 1, embedding_provider=KeywordEmbeddingProvider(), settings=settings)
    item = session.scalar(
        select(ContentItemRecord).where(ContentItemRecord.project_id == project.id)
    )
    assert QUOTE in item.text
    assert item.source_mode == "web_json"


def test_missing_reddit_permalink_does_not_promote_external_article_url(tmp_path):
    session = make_session()
    source = post()
    source["data"]["selftext"] = QUOTE
    source["data"].pop("permalink")
    source["data"]["url"] = "https://example.com/news-article"
    import_reddit_export(
        session,
        project_id=1,
        input_path=write_json(tmp_path, listing([source])),
        acquisition_method="web_json",
    )
    assert analyze(session, 1).extracted_signals == 1
    assert ReportRepository(session).list_evidence_items(1)[0].source_url is None


@pytest.mark.parametrize("body", [None, "Our new math tutoring needs are different in Zurich."])
def test_comment_import_uses_project_snapshot_and_preserves_missing_text(tmp_path, body):
    session = make_session()
    session.add(
        ResearchProjectRecord(
            project_id=2,
            slug="new-comment-import",
            topic="Zurich tutoring",
            languages=["en"],
            access_mode="personal",
        )
    )
    session.commit()
    comment = {
        "kind": "t1",
        "data": {
            "id": "c1",
            "link_id": "t3_abc",
            "parent_id": "t3_abc",
            "body": QUOTE,
            "permalink": "/r/zurich/comments/abc/title/c1/",
        },
    }
    import_reddit_export(
        session,
        project_id=1,
        input_path=write_json(tmp_path, listing([comment])),
        acquisition_method="web_json",
    )
    comment["data"]["body"] = body
    comment["data"].pop("permalink")
    import_reddit_export(
        session,
        project_id=2,
        input_path=write_json(tmp_path, listing([comment])),
        acquisition_method="dom",
    )
    settings = Settings(_env_file=None)
    run_filtering(session, 2, embedding_provider=KeywordEmbeddingProvider(), settings=settings)
    project = session.scalar(
        select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == 2)
    )
    item = session.scalar(
        select(ContentItemRecord).where(ContentItemRecord.project_id == project.id)
    )
    assert item.text == (body or "")
    assert item.source_mode == "dom"
    if body is not None:
        run_signal_extraction(session, 2, settings=settings)
        assert ReportRepository(session).list_evidence_items(project.id)[0].source_url is None
    else:
        assert item.final_status == "rejected"


def analyze(session, project_id):
    settings = Settings(_env_file=None)
    run_filtering(
        session, project_id, embedding_provider=KeywordEmbeddingProvider(), settings=settings
    )
    return run_signal_extraction(
        session,
        project_id,
        provider=DeterministicSignalProvider(
            fixture_output={
                "status": "extracted",
                "signals": [
                    {
                        "user_persona": "PARENT",
                        "user_problem": "Needs trusted math support.",
                        "explicit_need": "Find a tutor recommendation.",
                        "implicit_need": "Reduce school pressure.",
                        "emotional_tone": "worried",
                        "purchase_intent": "medium",
                        "trust_concern": True,
                        "price_concern": False,
                        "urgency": "medium",
                        "useful_quote": QUOTE,
                        "recommended_business_response": "Offer transparent curriculum support.",
                        "confidence": 0.86,
                    }
                ],
                "abstention_reason": None,
                "confidence": 0.86,
            }
        ),
        settings=settings,
    )


@pytest.mark.parametrize("method", ["web_json", "manual_web", "dom"])
def test_acquisition_method_survives_filtering_and_analysis(tmp_path, method, monkeypatch):
    for key in (
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
        "GOOGLE_CUSTOM_SEARCH_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    session = make_session()
    source = post()
    source["data"]["selftext"] = QUOTE
    import_reddit_export(
        session,
        project_id=1,
        input_path=write_json(tmp_path, listing([source])),
        acquisition_method=method,
    )
    summary = analyze(session, 1)
    assert summary.extracted_signals == 1
    assert session.scalar(select(ContentItemRecord)).source_mode == method
    assert session.scalar(select(MarketSignalRecord)).source_mode == method


@pytest.mark.parametrize("api_first", [True, False])
def test_api_and_import_projects_keep_independent_source_provenance(tmp_path, api_first):
    from app.reddit.repository import RedditCollectionRepository
    from app.reddit.models import RedditPostSnapshot
    from app.db.models import SearchQueryRecord

    session = make_session()
    session.add(
        ResearchProjectRecord(
            project_id=2,
            slug="api-project",
            topic="Zurich tutoring",
            languages=["en"],
            access_mode="personal",
        )
    )
    session.commit()
    source = post()
    source["data"]["selftext"] = QUOTE
    path = write_json(tmp_path, listing([source]))
    repository = RedditCollectionRepository(session)

    def api_ingest():
        project = repository.get_project_by_project_id(2)
        query = SearchQueryRecord(
            project_id=project.id, query="tutor", source="reddit", filters_json={}
        )
        session.add(query)
        session.flush()
        raw, _ = repository.upsert_raw_post(
            RedditPostSnapshot(
                reddit_post_id="abc",
                reddit_fullname="t3_abc",
                title="API title",
                body=QUOTE,
                permalink="/r/zurich/comments/abc/title/",
                raw_json={"id": "abc", "selftext": QUOTE},
            )
        )
        repository.link_project_post(
            project_db_id=project.id, run_id=None, search_query=query, request_id=None, raw_post=raw
        )

    if api_first:
        api_ingest()
    import_reddit_export(session, project_id=1, input_path=path, acquisition_method="manual_web")
    if not api_first:
        api_ingest()
    analyze(session, 1)
    analyze(session, 2)
    items = session.scalars(select(ContentItemRecord).order_by(ContentItemRecord.project_id)).all()
    assert [item.source_mode for item in items] == ["manual_web", "reddit_api"]
    assert session.scalar(select(RedditPostRawRecord)).title == (
        "API title" if api_first else "Math tutor"
    )
    assert ReportRepository(session).list_evidence_items(1)[0].source_mode == "manual_web"
    assert ReportRepository(session).list_evidence_items(2)[0].source_mode == "reddit_api"


def test_report_exports_links_distinct_capture_counts_and_partial_comment_caveats(tmp_path):
    session = make_session()
    source = post()
    source["data"]["selftext"] = QUOTE
    reply = {
        "kind": "t1",
        "data": {
            "id": "r2",
            "link_id": "t3_abc",
            "parent_id": "t1_c1",
            "body": QUOTE,
            "permalink": "/r/zurich/comments/abc/title/r2/",
        },
    }
    comment = {
        "kind": "t1",
        "data": {
            "id": "c1",
            "link_id": "t3_abc",
            "parent_id": "t3_abc",
            "body": QUOTE,
            "permalink": "/r/zurich/comments/abc/title/c1/",
            "replies": listing([reply]),
        },
    }
    more = {"kind": "more", "data": {"parent_id": "t3_abc", "count": 7, "children": ["x1"]}}
    path = write_json(tmp_path, [listing([source]), listing([comment, more])])
    for _ in range(2):
        import_reddit_export(
            session,
            project_id=1,
            input_path=path,
            acquisition_method="web_json",
            query="math tutor Zurich",
            sort="relevance",
            time_window="year",
            captured_at="2026-10-12T10:00:00Z",
            source_url="https://www.reddit.com/r/zurich/search/?q=tutor",
        )
    assert analyze(session, 1).extracted_signals == 3
    repository = ReportRepository(session)
    summary = repository.build_dataset_summary(1)
    assert summary.import_unique_posts == 1
    assert summary.import_unique_comments == 2
    assert summary.import_discussions == 1
    assert len(summary.import_batches) == 2
    assert summary.import_coverage["abc"]["captured_comments"] == 2
    assert summary.import_coverage["abc"]["comments_complete"] == "incomplete"
    evidence = repository.list_evidence_items(1)
    assert {item.source_url for item in evidence} == {
        "https://www.reddit.com/r/zurich/comments/abc/math_tutor/",
        "https://www.reddit.com/r/zurich/comments/abc/title/c1/",
        "https://www.reddit.com/r/zurich/comments/abc/title/r2/",
    }
    report_path = tmp_path / "synthetic-report.md"
    generate_market_report(session, 1, output_path=report_path)
    markdown, csv_path = export_report_evidence(session, 1, output_dir=tmp_path / "evidence")
    rendered = report_path.read_text()
    assert "saved Reddit JSON response" in rendered
    assert "Captured comments: 2" in rendered
    assert "incomplete" in rendered
    assert "math tutor Zurich" in rendered
    assert "more" in rendered
    assert "missing" in rendered.lower()
    assert evidence[0].source_url in markdown.read_text()
    with csv_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["source_url"] for row in rows} == {item.source_url for item in evidence}


@pytest.mark.parametrize(
    "method,description",
    [("manual_web", "selected saved webpage content"), ("dom", "only loaded page content")],
)
def test_comment_supplement_reports_unknown_coverage_and_rejects_missing_text(
    tmp_path, method, description
):
    session = make_session()
    rows = [
        {
            "type": "comment",
            "id": "c1",
            "post_id": "abc",
            "subreddit": "zurich",
            "title": None,
            "text": QUOTE,
            "created_utc": None,
            "score": None,
            "num_comments": None,
            "source_url": "/r/zurich/comments/abc/title/c1/",
        },
        {
            "type": "comment",
            "id": "c2",
            "post_id": "abc",
            "subreddit": "zurich",
            "title": None,
            "text": None,
            "created_utc": None,
            "score": None,
            "num_comments": None,
            "source_url": "",
        },
    ]
    import_reddit_export(
        session, project_id=1, input_path=write_json(tmp_path, rows), acquisition_method=method
    )
    assert analyze(session, 1).extracted_signals == 1
    summary = ReportRepository(session).build_dataset_summary(1)
    assert summary.import_unique_posts == 0
    assert summary.import_unique_comments == 2
    assert summary.content_status_counts == {"accepted": 1, "rejected": 1}
    assert summary.import_coverage == {
        "abc": {"comments_complete": "unknown", "captured_comments": 2}
    }
    output = tmp_path / f"{method}.md"
    generate_market_report(session, 1, output_path=output)
    markdown = output.read_text()
    assert description in markdown
    assert "unknown" in markdown
    assert "missing fields" in markdown
    assert "source_url: https://www.reddit.com/r/zurich/comments/abc/title/c1/" in markdown
