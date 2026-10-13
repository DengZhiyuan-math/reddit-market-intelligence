"""Offline export imports through the existing database and CLI."""

import json
from pathlib import Path

import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.cli import app
from app.db.base import Base
from app.db.models import (
    PipelineRunRecord,
    ProjectRedditPostRecord,
    RedditPostRawRecord,
    ResearchProjectRecord,
)


def make_session(database_url="sqlite:///:memory:"):
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        ResearchProjectRecord(
            project_id=1,
            slug="import-1",
            topic="Zurich tutoring",
            languages=["en"],
            access_mode="personal",
        )
    )
    session.commit()
    return session


def listing(children):
    return {"kind": "Listing", "data": {"children": children}}


def post():
    return {
        "kind": "t3",
        "data": {
            "id": "abc",
            "name": "t3_abc",
            "subreddit": "zurich",
            "title": "Math tutor",
            "selftext": "We need a math tutor in Zurich.",
            "num_comments": 42,
            "permalink": "/r/zurich/comments/abc/math_tutor/",
        },
    }


def write_json(tmp_path, payload):
    path = tmp_path / "export.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("payload", [[42], [None]])
def test_non_record_json_arrays_fail_with_schema_error_without_writes(tmp_path, payload):
    from app.reddit.export_import import import_reddit_export

    session = make_session()
    with pytest.raises(ValueError, match="Expected a Reddit Listing"):
        import_reddit_export(
            session,
            project_id=1,
            input_path=write_json(tmp_path, payload),
            acquisition_method="web_json",
        )
    assert session.scalars(select(PipelineRunRecord)).all() == []
    assert session.scalars(select(RedditPostRawRecord)).all() == []


def test_cli_imports_listing_without_acquisition_credentials(tmp_path: Path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'local.db'}"
    session = make_session(database_url)
    for key in (
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
        "GOOGLE_CUSTOM_SEARCH_API_KEY",
        "GOOGLE_CUSTOM_SEARCH_ENGINE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)
    path = write_json(tmp_path, listing([post()]))

    result = CliRunner().invoke(
        app,
        [
            "reddit",
            "import-export",
            "--project-id",
            "1",
            "--input-path",
            str(path),
            "--acquisition-method",
            "web_json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Captured posts: 1" in result.output
    raw = session.scalar(select(RedditPostRawRecord))
    assert raw.reddit_post_id == "abc"
    assert raw.body == "We need a math tutor in Zurich."
    assert raw.raw_json["source_snapshot"]["num_comments"] == 42
    association = session.scalar(select(ProjectRedditPostRecord))
    assert association.filters_json["acquisition_method"] == "web_json"
    run = session.scalar(select(PipelineRunRecord))
    assert run.status == "completed"
    assert run.run_config["captured_at"] is None
    assert run.summary["captured_comments"] == 0


def test_nested_listing_counts_returned_replies_and_more_not_num_comments(tmp_path):
    from app.reddit.export_import import import_reddit_export
    from app.db.models import RedditCommentRawRecord

    reply = {
        "kind": "t1",
        "data": {"id": "r2", "link_id": "t3_abc", "parent_id": "t1_c1", "body": "A useful reply"},
    }
    comment = {
        "kind": "t1",
        "data": {
            "id": "c1",
            "link_id": "t3_abc",
            "parent_id": "t3_abc",
            "body": "Need help",
            "replies": listing([reply]),
        },
    }
    more = {"kind": "more", "data": {"parent_id": "t3_abc", "count": 7, "children": ["x1", "x2"]}}
    session = make_session()
    path = write_json(tmp_path, [listing([post()]), listing([comment, more])])
    summary = import_reddit_export(
        session, project_id=1, input_path=path, acquisition_method="web_json"
    )
    session.commit()

    assert summary.captured_comments == 2
    assert summary.nested_replies == 1
    assert summary.post_coverage["abc"] == {
        "captured_comments": 2,
        "source_num_comments": 42,
        "comments_complete": "incomplete",
        "more_markers": 1,
        "known_omitted_count": 7,
    }
    assert summary.more_markers[0]["children"] == ["x1", "x2"]
    assert (
        session.scalar(
            select(RedditCommentRawRecord).where(RedditCommentRawRecord.reddit_comment_id == "r2")
        ).depth
        == 1
    )
    assert "incomplete" in " ".join(summary.warnings)


def test_author_csv_bom_multiline_and_formula_prefix_preserves_unknowns(tmp_path):
    from app.reddit.export_import import import_reddit_export
    from app.db.models import RedditCommentRawRecord

    path = tmp_path / "export.csv"
    path.write_text(
        'type,id,post_id,subreddit,title,text,created_utc,score,num_comments,source_url\npost,t3_ABC,abc,zurich,Math tutor,"\'=Need help\non Monday",,3,42,https://www.reddit.com/r/zurich/comments/abc/math_tutor/\ncomment,t1_C1,t3_abc,zurich,,"Real \'text",,,,https://www.reddit.com/r/zurich/comments/abc/math_tutor/c1/\n',
        encoding="utf-8-sig",
    )
    session = make_session()
    summary = import_reddit_export(
        session, project_id=1, input_path=path, acquisition_method="manual_web"
    )
    assert summary.captured_posts == 1
    assert summary.captured_comments == 1
    raw = session.scalar(select(RedditPostRawRecord))
    assert raw.reddit_post_id == "abc"
    assert raw.body == "=Need help\non Monday"
    assert raw.created_utc is None
    assert raw.author is None
    comment = session.scalar(select(RedditCommentRawRecord))
    assert comment.body == "Real 'text"
    assert comment.depth is None
    assert comment.parent_id is None
    assert summary.missing_fields["created_utc"] == 2
    assert summary.post_coverage["abc"]["comments_complete"] == "unknown"
    assert "formula" in " ".join(summary.warnings)


@pytest.mark.parametrize(
    "text,expected", [("'  =Need help", "  =Need help"), ("'\tPlain text", "'\tPlain text")]
)
def test_author_csv_prefix_matches_formula_rule_without_stripping_plain_quotes(
    tmp_path, text, expected
):
    import csv
    from app.reddit.export_import import import_reddit_export

    path = tmp_path / "export.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "type",
                "id",
                "post_id",
                "subreddit",
                "title",
                "text",
                "created_utc",
                "score",
                "num_comments",
                "source_url",
            ]
        )
        writer.writerow(
            [
                "post",
                "abc",
                "abc",
                "zurich",
                "Math tutor",
                text,
                "",
                "",
                "",
                "/r/zurich/comments/abc/title/",
            ]
        )
    session = make_session()
    import_reddit_export(session, project_id=1, input_path=path, acquisition_method="web_json")
    assert session.scalar(select(RedditPostRawRecord)).body == expected


@pytest.mark.parametrize(
    "change,field",
    [
        ({"id": "web_abc"}, "id"),
        ({"name": "t1_abc"}, "name"),
        ({"permalink": "https://evil.test/r/zurich/comments/abc/title/"}, "URL"),
        ({"permalink": "/r/zurich/comments/xyz/title/"}, "URL"),
        ({"score": True}, "score"),
        ({"selftext": ["bad"]}, "selftext"),
    ],
)
def test_full_validation_rejects_bad_later_item_before_any_writes(tmp_path, change, field):
    from app.reddit.export_import import import_reddit_export

    session = make_session()
    invalid = post()
    invalid["data"].update(change)
    path = write_json(tmp_path, listing([post(), invalid]))
    with pytest.raises(ValueError, match=field):
        import_reddit_export(session, project_id=1, input_path=path, acquisition_method="web_json")
    session.commit()
    assert session.scalars(select(PipelineRunRecord)).all() == []
    assert session.scalars(select(RedditPostRawRecord)).all() == []
    assert session.scalars(select(ProjectRedditPostRecord)).all() == []


def test_repeat_dedup_canonical_ids_and_project_provenance_keep_original_batch_history(tmp_path):
    from app.reddit.export_import import import_reddit_export

    session = make_session()
    session.add(
        ResearchProjectRecord(
            project_id=2, slug="import-2", topic="Other project", access_mode="personal"
        )
    )
    session.commit()
    original = post()
    duplicate = post()
    duplicate["data"]["id"] = "t3_ABC"
    first = import_reddit_export(
        session,
        project_id=1,
        input_path=write_json(tmp_path, listing([original, duplicate])),
        acquisition_method="web_json",
        query="original query",
    )
    changed = post()
    changed["data"]["selftext"] = "Later changed text"
    path = write_json(tmp_path, listing([changed]))
    second = import_reddit_export(session, project_id=1, input_path=path, acquisition_method="dom")
    third = import_reddit_export(
        session, project_id=2, input_path=path, acquisition_method="manual_web"
    )
    session.commit()
    assert first.captured_posts == 1
    assert first.in_file_duplicates == 1
    assert second.duplicate_posts == 1
    assert second.new_post_links == 0
    assert third.new_post_links == 1
    assert session.scalar(select(RedditPostRawRecord)).body == "We need a math tutor in Zurich."
    associations = session.scalars(
        select(ProjectRedditPostRecord).order_by(ProjectRedditPostRecord.id)
    ).all()
    assert [row.filters_json["acquisition_method"] for row in associations] == [
        "web_json",
        "manual_web",
    ]
    assert associations[0].query == "original query"
    runs = session.scalars(select(PipelineRunRecord).order_by(PipelineRunRecord.id)).all()
    assert len(runs) == 3
    assert (
        runs[1].run_config["source_snapshot"]["data"]["children"][0]["data"]["selftext"]
        == "Later changed text"
    )
    assert runs[1].summary["items"] == [
        {
            "type": "post",
            "id": "abc",
            "post_id": "abc",
            "source_url": "https://www.reddit.com/r/zurich/comments/abc/math_tutor/",
        }
    ]


@pytest.mark.parametrize(
    "case", ["parent", "link", "more", "conflict", "timestamp", "html", "error", "row"]
)
def test_invalid_export_conditions_are_actionable_and_atomic(tmp_path, case):
    from app.reddit.export_import import import_reddit_export

    session = make_session()
    options = {}
    payload = [
        listing([post()]),
        listing(
            [
                {
                    "kind": "t1",
                    "data": {
                        "id": "c1",
                        "link_id": "t3_abc",
                        "parent_id": "t3_abc",
                        "body": "Help",
                    },
                }
            ]
        ),
    ]
    if case == "parent":
        payload[1]["data"]["children"][0]["data"]["parent_id"] = "t3_xyz"
    elif case == "link":
        payload[1]["data"]["children"][0]["data"]["link_id"] = "t3_xyz"
    elif case == "more":
        payload[1]["data"]["children"] = [
            {"kind": "more", "data": {"parent_id": "t3_abc", "count": -1, "children": []}}
        ]
    elif case == "conflict":
        duplicate = post()
        duplicate["data"]["title"] = "Conflict"
        payload[0]["data"]["children"].append(duplicate)
    elif case == "timestamp":
        options["captured_at"] = "not a timestamp"
    elif case == "error":
        payload = {"error": 403, "message": "Forbidden"}
    elif case == "row":
        payload = [
            {
                "type": "comment",
                "id": "c1",
                "post_id": "abc",
                "subreddit": "zurich",
                "title": "",
                "text": None,
                "created_utc": None,
                "score": "1e4",
                "num_comments": None,
                "source_url": "",
            }
        ]
    path = write_json(tmp_path, payload)
    if case == "html":
        path.write_text("<html>Log in</html>")
    with pytest.raises(ValueError):
        import_reddit_export(
            session, project_id=1, input_path=path, acquisition_method="dom", **options
        )
    session.commit()
    assert session.scalars(select(PipelineRunRecord)).all() == []
    assert session.scalars(select(RedditPostRawRecord)).all() == []


def test_dry_run_has_same_coverage_and_no_writes(tmp_path):
    from app.reddit.export_import import import_reddit_export

    session = make_session()
    path = write_json(tmp_path, listing([post()]))
    dry = import_reddit_export(
        session, project_id=1, input_path=path, acquisition_method="dom", dry_run=True
    )
    session.commit()
    assert dry.run_id is None
    assert session.scalars(select(PipelineRunRecord)).all() == []
    real = import_reddit_export(session, project_id=1, input_path=path, acquisition_method="dom")
    assert dry.post_coverage == real.post_coverage
    assert dry.items == real.items
    assert dry.missing_fields == real.missing_fields


def test_comment_only_rows_do_not_fabricate_post_and_transaction_rolls_back_database_failure(
    tmp_path,
):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from app.db.models import RedditCommentRawRecord
    from app.reddit.export_import import import_reddit_export

    session = make_session()
    row = {
        "type": "comment",
        "id": "c1",
        "post_id": "abc",
        "subreddit": "zurich",
        "title": None,
        "text": "We need a tutor in Zurich.",
        "created_utc": None,
        "score": None,
        "num_comments": None,
        "source_url": "/r/zurich/comments/abc/title/c1/",
    }
    path = write_json(tmp_path, [row])
    summary = import_reddit_export(
        session,
        project_id=1,
        input_path=path,
        acquisition_method="dom",
        captured_at="2026-10-12T12:00:00+02:00",
    )
    session.commit()
    assert summary.captured_posts == 0
    assert summary.captured_comments == 1
    assert session.scalars(select(RedditPostRawRecord)).all() == []
    assert (
        session.scalar(select(RedditCommentRawRecord)).permalink
        == "https://www.reddit.com/r/zurich/comments/abc/title/c1/"
    )
    assert (
        session.scalar(select(PipelineRunRecord)).run_config["captured_at"]
        == "2026-10-12T10:00:00+00:00"
    )

    failing_session = make_session()
    failing_session.execute(
        text(
            "CREATE TRIGGER reject_comments BEFORE INSERT ON reddit_comments_raw BEGIN SELECT RAISE(ABORT, 'synthetic DB failure'); END"
        )
    )
    failing_session.commit()
    with pytest.raises(IntegrityError):
        import_reddit_export(
            failing_session, project_id=1, input_path=path, acquisition_method="dom"
        )
    failing_session.commit()
    assert failing_session.scalars(select(PipelineRunRecord)).all() == []
    assert failing_session.scalars(select(RedditCommentRawRecord)).all() == []


@pytest.mark.parametrize("payload", [listing([]), []])
def test_empty_exports_are_valid_and_report_no_evidence(tmp_path, payload):
    from app.reddit.export_import import import_reddit_export

    summary = import_reddit_export(
        make_session(),
        project_id=1,
        input_path=write_json(tmp_path, payload),
        acquisition_method="web_json",
    )
    assert summary.captured_posts == 0
    assert summary.captured_comments == 0
    assert any("empty" in warning for warning in summary.warnings)


def test_parent_comment_from_another_post_is_rejected_before_writes(tmp_path):
    from app.reddit.export_import import import_reddit_export

    rows = [
        {
            "type": "comment",
            "id": "c1",
            "post_id": "abc",
            "subreddit": "zurich",
            "title": "",
            "text": "First",
            "created_utc": None,
            "score": None,
            "num_comments": None,
            "source_url": "",
            "parent_id": "t3_abc",
        },
        {
            "type": "comment",
            "id": "c2",
            "post_id": "xyz",
            "subreddit": "zurich",
            "title": "",
            "text": "Wrong post parent",
            "created_utc": None,
            "score": None,
            "num_comments": None,
            "source_url": "",
            "parent_id": "t1_c1",
        },
    ]
    session = make_session()
    with pytest.raises(ValueError, match="parent_id"):
        import_reddit_export(
            session,
            project_id=1,
            input_path=write_json(tmp_path, rows),
            acquisition_method="manual_web",
        )
    assert session.scalars(select(PipelineRunRecord)).all() == []
