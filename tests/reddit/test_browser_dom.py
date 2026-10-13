"""Synthetic connected-boundary tests; no actual browser operation occurs."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.llm.transport import RunBudget


def test_connected_boundary_connects_before_task_tab_and_bounds_capture(monkeypatch, tmp_path):
    from app.reddit.browser_dom import ConnectedBrowser

    commands = []

    def run(args, **kwargs):
        commands.append(args)
        assert kwargs["shell"] is False
        assert kwargs["timeout"] <= 10
        assert json.loads(Path(args[args.index("--config") + 1]).read_text()) == {}
        assert "AGENT_BROWSER_RESTORE" not in kwargs["env"]
        assert "HTTPS_PROXY" not in kwargs["env"]
        if "connect" in args:
            # Actual v0.33.1 explicit-CDP response: "launched" is also set
            # when the connection reuses the prepared external browser.
            data = {
                "launched": True,
                "reused": True,
                "lifecycle": {
                    "launched": True,
                    "reused": True,
                    "relaunchedBrowser": False,
                    "restoreStatus": "not_configured",
                },
            }
        elif "eval" in args:
            assert "fetch(" not in kwargs["input"]
            data = {"result": {"html": "<main></main>", "barrier": False}}
        elif "title" in args:
            data = {"title": "Reddit"}
        elif "url" in args:
            data = {"url": "https://www.reddit.com/r/zurich/search/?q=math"}
        elif "snapshot" in args:
            data = {"snapshot": "main"}
        else:
            data = {}
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({"success": True, "data": data}), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("AGENT_BROWSER_RESTORE", "not-authorized")
    monkeypatch.setenv("HTTPS_PROXY", "not-authorized")
    settings = Settings(
        _env_file=None,
        browser_dom_cdp_url="http://127.0.0.1:9223",
        browser_dom_session="reddit-dom-test",
    )
    budget = RunBudget(max_seconds=10)
    with ConnectedBrowser(settings, budget) as browser:
        capture = browser.capture("https://www.reddit.com/r/zurich/search/?q=math")
    assert "connect" in commands[0]
    assert commands[1][commands[1].index("tab") + 1] == "new"
    assert capture["html"] == "<main></main>"
    assert budget.browser_navigations == 1
    assert budget.browser_operations == len(commands)
    assert not any(
        "close" in command or "--profile" in command or "--restore" in command
        for command in commands
    )


FIXTURES = Path("tests/fixtures/reddit_dom")


def page(name, url, title="Reddit"):
    return {"html": (FIXTURES / name).read_text(), "url": url, "title": title, "barrier": False}


def test_literal_dom_candidates_and_own_bodies_exclude_noise_and_unknowns():
    from app.reddit.browser_dom import parse_search_capture, parse_discussion_capture

    search = page("search.html", "https://www.reddit.com/r/zurich/search/?q=tutor&captcha=1")
    assert parse_search_capture(search) == [
        "https://www.reddit.com/r/zurich/comments/abc/synthetic/"
    ]
    discussion = page("discussion.html", "https://www.reddit.com/r/zurich/comments/abc/synthetic/")
    rows = parse_discussion_capture(discussion, expected_post_id="abc")
    assert [row["id"] for row in rows] == ["abc", "c1", "r1"]
    assert rows[0]["text"] == "Can anyone recommend a math tutor in Zurich?"
    assert rows[0]["created_utc"] == 1635704141
    assert rows[0]["num_comments"] == 3
    assert rows[1]["parent_id"] is None
    assert rows[2]["parent_id"] == "t1_c1"
    assert rows[2]["created_utc"] is None
    assert not any("noise" in row["text"] or "Hidden" in row["text"] for row in rows)


@pytest.mark.parametrize("case", ["barrier", "login", "external", "identity", "layout"])
def test_barrier_and_unsupported_captures_fail_without_evidence(case):
    from app.reddit.browser_dom import parse_discussion_capture, BrowserDomError

    capture = page("discussion.html", "https://www.reddit.com/r/zurich/comments/abc/synthetic/")
    if case == "barrier":
        capture = page("blocked.html", capture["url"], "Reddit - Prove your humanity")
    elif case == "login":
        capture["url"] = "https://www.reddit.com/login/"
    elif case == "external":
        capture["url"] = "https://evil.example.test/r/zurich/comments/abc/synthetic/"
    elif case == "identity":
        capture["html"] = capture["html"].replace('id="t3_abc"', 'id="t3_wrong"')
    elif case == "layout":
        capture["html"] = "<main><article>Whole page text is not evidence.</article></main>"
    with pytest.raises((PermissionError, BrowserDomError)):
        parse_discussion_capture(capture, expected_post_id="abc")


@pytest.mark.parametrize("case", ["timeout", "output", "error", "launch"])
def test_connected_boundary_fails_closed_on_runtime_errors(monkeypatch, case):
    from app.reddit.browser_dom import ConnectedBrowser, BrowserDomError, MAX_CAPTURE_CHARS

    def run(args, **kwargs):
        if case == "timeout":
            raise subprocess.TimeoutExpired(args, 1)
        payload = {
            "success": case != "error",
            "data": {"lifecycle": {"launched": case == "launch"}},
        }
        return SimpleNamespace(
            returncode=0,
            stdout="x" * (MAX_CAPTURE_CHARS + 1) if case == "output" else json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(BrowserDomError):
        with ConnectedBrowser(
            Settings(_env_file=None, browser_dom_cdp_url="http://127.0.0.1:9223"), RunBudget()
        ):
            pass


def test_automatic_dom_acquisition_imports_loaded_rows_and_only_new_scope(monkeypatch, tmp_path):
    from app.reddit.browser_dom import acquire_browser_dom, ConnectedBrowser
    from tests.reddit.test_export_import import make_session
    from app.db.models import PipelineRunRecord, RedditPostRawRecord, RedditCommentRawRecord
    from sqlalchemy import select
    from tests.reddit.test_public_json import strategy

    def capture(self, url):
        return page("search.html", url) if "/search/" in url else page("discussion.html", url)

    monkeypatch.setattr(ConnectedBrowser, "__enter__", lambda self: self)
    monkeypatch.setattr(ConnectedBrowser, "capture", capture)
    session = make_session()
    settings = Settings(_env_file=None, browser_dom_cdp_url="http://127.0.0.1:9223")
    result = acquire_browser_dom(
        session,
        project_id=1,
        queries=strategy(),
        settings=settings,
        budget=RunBudget(max_items=3, max_requests=2),
        max_queries=1,
        output_dir=tmp_path / "captures",
    )
    assert result.status == "completed"
    assert result.scope == {"reddit_post": ["abc"], "reddit_comment": ["c1", "r1"]}
    assert (
        session.scalar(select(RedditPostRawRecord)).body
        == "Can anyone recommend a math tutor in Zurich?"
    )
    assert len(session.scalars(select(RedditCommentRawRecord)).all()) == 2
    repeat = acquire_browser_dom(
        session,
        project_id=1,
        queries=strategy(),
        settings=settings,
        budget=RunBudget(max_items=3, max_requests=2),
        max_queries=1,
        output_dir=tmp_path / "captures",
    )
    assert repeat.status == "no_evidence"
    run = session.get(PipelineRunRecord, result.run_id)
    assert run.summary["captures"][0]["loaded_comments"] == 2
    assert run.summary["captures"][0]["comments_complete"] == "unknown"
    assert "Advert" not in Path(run.summary["captures"][0]["artifact"]).read_text()


@pytest.mark.parametrize("failure", ["blocked", "layout", "items", "navigation", "operations"])
def test_dom_failure_or_budget_preserves_stale_records_and_stops(monkeypatch, tmp_path, failure):
    from app.reddit.browser_dom import acquire_browser_dom, ConnectedBrowser
    from tests.test_pipeline import imported_session
    from tests.reddit.test_public_json import strategy
    from app.db.models import PipelineRunRecord

    session = imported_session(tmp_path)

    def capture(self, url):
        self.budget.browser_operation(navigation=True)
        if failure == "blocked":
            return page("blocked.html", url, "Reddit - Prove your humanity")
        result = page("search.html", url) if "/search/" in url else page("discussion.html", url)
        if failure == "layout" and "/search/" not in url:
            result["html"] = "<main>Unsupported layout</main>"
        return result

    monkeypatch.setattr(ConnectedBrowser, "__enter__", lambda self: self)
    monkeypatch.setattr(ConnectedBrowser, "capture", capture)
    result = acquire_browser_dom(
        session,
        project_id=1,
        queries=strategy(),
        settings=Settings(_env_file=None, browser_dom_cdp_url="http://127.0.0.1:9223"),
        budget=RunBudget(
            max_items=1 if failure == "items" else 3,
            max_requests=1 if failure == "navigation" else 2,
            max_browser_operations=1 if failure == "operations" else 80,
        ),
        max_queries=1,
        output_dir=tmp_path / "captures",
    )
    assert result.status in {"blocked", "failed"}
    assert result.scope == {"reddit_post": [], "reddit_comment": []}
    session.rollback()
    assert session.get(PipelineRunRecord, result.run_id).status == result.status
    assert not (tmp_path / "captures").exists()
