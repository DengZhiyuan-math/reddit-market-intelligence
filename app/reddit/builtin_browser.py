"""Codex in-app browser task and capture handoff. No browser subprocesses."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlsplit, urlencode

from app.reddit.browser_dom import (
    DOM_SCRIPT,
    BrowserDomError,
    _discussion_id,
    parse_discussion_capture,
    parse_search_capture,
)
from app.reddit.export_import import import_reddit_export
from app.reddit.public_json import search_url
from app.reddit.repository import RedditCollectionRepository
from app.db.models import PipelineRunRecord


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Browser timestamps require a timezone")
    return stamp


def prepare_browser_task(
    *, project_id, plan_id, queries, since, until, max_items=100, max_queries=3, max_discussions=16
):
    """Prepare finite search instructions for the Codex browser tools."""
    if not (1 <= max_items <= 100 and 1 <= max_queries <= 24 and 1 <= max_discussions <= 100):
        raise ValueError("Invalid browser task limits")
    if _stamp(since) >= _stamp(until):
        raise ValueError("Browser window must have since before until")
    urls = []
    for query in list(queries)[:max_queries]:
        parsed = urlsplit(search_url(query, 1))
        urls.append(
            "https://www.reddit.com"
            + parsed.path.replace("search.json", "search/")
            + "?"
            + urlencode(
                dict(
                    q=query.query,
                    restrict_sr="on",
                    sort=query.sort,
                    t=query.time_filter,
                    type="posts",
                )
            )
        )
    return dict(
        version="builtin-browser-dom.v1",
        browser="gpt_in_app_browser",
        project_id=project_id,
        plan_id=plan_id,
        since=since,
        until=until,
        max_items=max_items,
        max_discussions=max_discussions,
        search_urls=urls,
        capture_script=DOM_SCRIPT,
        instructions=[
            "Use cua_repl with the Codex in-app browser. Do not launch Chrome or use CDP.",
            "Open planned searches. Follow observed discussion links. Read current page state after navigation.",
            "Evaluate capture_script read-only. Add url, title and captured_at (UTC ISO timestamp).",
            "Save task, searches and discussions as one JSON bundle using local file tools.",
            "Stop on verification, login or blocked pages and request human access. Do not solve or bypass challenges.",
            "Only loaded originals count. Record visible omitted-reply controls. Complete comment coverage is unknown.",
        ],
    )


def import_browser_capture(
    session,
    *,
    project_id,
    plan_id,
    input_path: Path,
    max_items=100,
    expected_task: dict | None = None,
):
    """Validate all captures before importing original, dated records atomically."""
    if input_path.stat().st_size > 22000000:
        raise BrowserDomError("Oversized browser bundle")
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    task = payload.get("task", expected_task)
    if not isinstance(task, dict):
        raise BrowserDomError("Capture task missing; resume a prepared browser run")
    if expected_task is not None and task != expected_task:
        raise BrowserDomError("Capture task differs from the frozen browser task")
    if (
        task["version"] != "builtin-browser-dom.v1"
        or task["browser"] != "gpt_in_app_browser"
        or task["project_id"] != project_id
        or task["plan_id"] != plan_id
    ):
        raise BrowserDomError("Browser task does not match project and selected plan")
    since, until = _stamp(task["since"]), _stamp(task["until"])
    if since >= until or not 1 <= task["max_items"] <= 100:
        raise BrowserDomError("Invalid browser window or item limit")
    searches, discussions = payload["searches"], payload["discussions"]
    if (
        not 1 <= len(task["search_urls"]) <= 24
        or len(searches) > len(task["search_urls"])
        or not 1 <= task["max_discussions"] <= 100
        or len(discussions) > task["max_discussions"]
    ):
        raise BrowserDomError("Browser capture limit exceeded")
    discovered, searched = set(), set()
    for capture in searches:
        if capture["url"] not in task["search_urls"] or capture["url"] in searched:
            raise BrowserDomError("Unplanned or duplicate browser search")
        _stamp(capture["captured_at"])
        searched.add(capture["url"])
        discovered.update(_discussion_id(url) for url in parse_search_capture(capture))
    rows, seen, coverage = [], set(), []
    excluded = {"unknown_timestamp": 0, "outside_window": 0, "missing_text": 0}
    for capture in discussions:
        pid = _discussion_id(capture["url"])
        if pid not in discovered or pid in seen:
            raise BrowserDomError("Discussion was not discovered in this task or was duplicated")
        seen.add(pid)
        _stamp(capture["captured_at"])
        parsed = parse_discussion_capture(capture, expected_post_id=pid)
        accepted = []
        for row in parsed:
            reason = (
                "unknown_timestamp"
                if row["created_utc"] is None
                else "outside_window"
                if not since.timestamp() <= row["created_utc"] <= until.timestamp()
                else "missing_text"
                if not row["text"]
                else None
            )
            if reason:
                excluded[reason] += 1
                continue
            accepted.append(
                {**row, "captured_at": capture["captured_at"], "browser": "gpt_in_app_browser"}
            )
        # A comment is only accepted together with its in-window original post.
        if not accepted or accepted[0]["type"] != "post":
            continue
        rows.extend(accepted)
        coverage.append(
            dict(
                post_id=pid,
                source_url=parsed[0]["source_url"],
                source_num_comments=parsed[0]["num_comments"],
                loaded_comments=len(parsed) - 1,
                retained_comments=len(accepted) - 1,
                comments_complete="unknown",
                omitted_controls=capture.get("omitted_controls", []),
                captured_at=capture["captured_at"],
                html_sha256=hashlib.sha256(capture["html"].encode()).hexdigest(),
            )
        )
    if len(rows) > min(task["max_items"], max_items):
        raise BrowserDomError("Browser record limit exceeded; prepare a smaller capture bundle")
    repo = RedditCollectionRepository(session)
    project = repo.get_project_by_project_id(project_id)
    before = repo.project_source_ids(project.id)
    metadata = dict(
        browser="gpt_in_app_browser",
        window=dict(since=task["since"], until=task["until"]),
        bundle_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
        searches=len(searches),
        discussions=len(discussions),
        records=len(rows),
        coverage=coverage,
        excluded=excluded,
        internal_http_requests=None,
    )
    if not rows:
        return SimpleNamespace(
            status="no_evidence",
            run_id=None,
            scope={},
            reason="No dated original DOM evidence in the window",
            metadata=metadata,
        )
    with TemporaryDirectory(prefix="reddit-builtin-") as directory:
        path = Path(directory) / "rows.json"
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        with session.begin_nested():
            summary = import_reddit_export(
                session,
                project_id=project_id,
                input_path=path,
                acquisition_method="dom",
                time_window=task["since"] + "/" + task["until"],
            )
            run = session.get(PipelineRunRecord, summary.run_id)
            run.run_config = {
                **run.run_config,
                "browser": "gpt_in_app_browser",
                "source_bundle_sha256": metadata["bundle_sha256"],
                "captured_at": max(capture["captured_at"] for capture in discussions),
            }
            run.summary = {
                **run.summary,
                "browser_capture": metadata,
                "post_coverage": {
                    entry["post_id"]: {**run.summary["post_coverage"][entry["post_id"]], **entry}
                    for entry in coverage
                },
            }
    after = repo.project_source_ids(project.id)
    scope = {
        kind: [
            row["id"]
            for row in rows
            if row["type"] == label and row["id"] in after[kind] - before[kind]
        ]
        for kind, label in (("reddit_post", "post"), ("reddit_comment", "comment"))
    }
    return SimpleNamespace(
        status="completed" if any(scope.values()) else "no_evidence",
        run_id=summary.run_id,
        scope=scope,
        metadata=metadata,
        reason=None if any(scope.values()) else "No newly associated DOM evidence",
    )
