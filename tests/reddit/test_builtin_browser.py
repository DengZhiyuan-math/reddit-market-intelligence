"""Built-in browser handoff uses the existing DOM parser and importer."""

import json
import pytest

from app.reddit.builtin_browser import prepare_browser_task, import_browser_capture
from tests.reddit.test_browser_dom import page
from tests.reddit.test_export_import import make_session
from app.topic_planning.models import PlannedSearchQuery


def test_builtin_capture_imports_originals_without_connected_browser(tmp_path):
    session = make_session()
    task = prepare_browser_task(
        project_id=1,
        plan_id=7,
        queries=[
            PlannedSearchQuery(
                subreddit="zurich", query="tutor", sort="new", time_filter="year", rationale="Test"
            )
        ],
        since="2025-10-12T00:00:00+02:00",
        until="2026-10-12T18:00:00Z",
        max_items=20,
        max_queries=1,
    )
    search = page("search.html", task["search_urls"][0], "Search")
    discussion = page(
        "discussion.html", "https://www.reddit.com/r/zurich/comments/abc/tutor/", "Tutor"
    )
    discussion["html"] = discussion["html"].replace("2021-10-31", "2026-10-01")
    search["captured_at"] = discussion["captured_at"] = "2026-10-12T18:01:00Z"
    path = tmp_path / "capture.json"
    path.write_text(json.dumps({"task": task, "searches": [search], "discussions": [discussion]}))
    result = import_browser_capture(session, project_id=1, plan_id=7, input_path=path)
    assert result.status == "completed"
    assert result.scope == {"reddit_post": ["abc"], "reddit_comment": ["c1"]}
    assert result.metadata["browser"] == "gpt_in_app_browser"
    assert result.metadata["coverage"][0]["comments_complete"] == "unknown"
    assert result.metadata["excluded"]["unknown_timestamp"] == 1
    repeat = import_browser_capture(session, project_id=1, plan_id=7, input_path=path)
    assert repeat.status == "no_evidence"
    assert not any(repeat.scope.values())


@pytest.mark.parametrize("failure", ["barrier", "unplanned", "wrong_project", "item_limit"])
def test_builtin_invalid_bundle_does_not_import_partial_evidence(tmp_path, failure):
    from app.reddit.repository import RedditCollectionRepository
    from app.reddit.browser_dom import BrowserDomError

    session = make_session()
    task = prepare_browser_task(
        project_id=1,
        plan_id=7,
        queries=[PlannedSearchQuery(subreddit="zurich", query="tutor", rationale="Test")],
        since="2025-10-12T00:00:00Z",
        until="2026-10-12T18:00:00Z",
    )
    search = page("search.html", task["search_urls"][0])
    discussion = page("discussion.html", "https://www.reddit.com/r/zurich/comments/abc/tutor/")
    discussion["html"] = discussion["html"].replace("2021-10-31", "2026-10-01")
    search["captured_at"] = discussion["captured_at"] = "2026-10-12T18:01:00Z"
    if failure == "barrier":
        discussion["barrier"] = True
    elif failure == "unplanned":
        search["url"] = "https://www.reddit.com/r/zurich/search/?q=other"
    elif failure == "wrong_project":
        task["project_id"] = 2
    else:
        task["max_items"] = 1
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(dict(task=task, searches=[search], discussions=[discussion])))
    with pytest.raises((BrowserDomError, PermissionError)):
        import_browser_capture(session, project_id=1, plan_id=7, input_path=path)
    assert RedditCollectionRepository(session).project_source_ids(1) == {
        "reddit_post": set(),
        "reddit_comment": set(),
    }
