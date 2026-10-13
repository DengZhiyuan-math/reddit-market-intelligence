"""Project evidence context must not leak across captures or projects."""

import json
from sqlalchemy import select
from app.db.models import ContentItemRecord, RedditPostRawRecord, ResearchProjectRecord
from app.processing.repository import ProcessingRepository
from app.reddit.export_import import import_reddit_export
from tests.reddit.test_export_import import make_session


def test_context_uses_scoped_snapshots_and_keeps_unassociated_parents_unknown(tmp_path):
    session = make_session()
    session.add(
        ResearchProjectRecord(project_id=2, slug="other", topic="Other", access_mode="personal")
    )
    session.flush()
    path = tmp_path / "rows.json"

    def row(kind, rid, pid, text, parent=None):
        return dict(
            type=kind,
            id=rid,
            post_id=pid,
            text=text,
            title="First title" if kind == "post" else None,
            subreddit="zurich",
            created_utc=None,
            score=None,
            num_comments=None,
            parent_id=parent,
            source_url=f"https://www.reddit.com/r/zurich/comments/{pid}/source/"
            + (rid + "/" if kind == "comment" else ""),
        )

    def capture(project_id, rows):
        path.write_text(json.dumps(rows))
        import_reddit_export(
            session, project_id=project_id, input_path=path, acquisition_method="dom"
        )

    capture(
        1,
        [
            row("post", "abc", "abc", "First parent body"),
            row("comment", "c1", "abc", "Parent reply", "t3_abc"),
            row("comment", "c2", "abc", "Current reply", "t1_c1"),
        ],
    )
    capture(2, [row("post", "def", "def", "Private other project context")])
    capture(1, [row("comment", "c3", "def", "No local parent", "t3_def")])
    raw = session.scalar(
        select(RedditPostRawRecord).where(RedditPostRawRecord.reddit_post_id == "abc")
    )
    raw.body = "Later global body must not replace this capture"
    project = session.scalar(
        select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == 1)
    )
    repo = ProcessingRepository(session)
    item = ContentItemRecord(project_id=project.id, source_type="reddit_comment", source_id="c2")
    context = repo.get_source_context(item)
    assert context["parent_post"]["text"] == "First parent body"
    assert context["parent_comment"]["text"] == "Parent reply"
    item.source_id = "c3"
    assert repo.get_source_context(item)["parent_post"] is None
    item.source_id = "missing"
    assert repo.get_source_context(item)["parent_comment"] is None
