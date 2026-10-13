"""Explicit public JSON acquisition. No pagination, cookies or access bypass."""

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

import requests
from sqlalchemy.orm import Session

from app.llm.transport import BudgetExceeded, RunBudget
from app.reddit.export_import import import_reddit_export
from app.reddit.repository import RedditCollectionRepository


@dataclass
class AcquisitionResult:
    status: str
    run_id: int
    scope: dict[str, list[str]]
    reason: str | None = None


def search_url(query, limit):
    if (
        not re.fullmatch(r"[A-Za-z0-9_]{2,21}", query.subreddit)
        or query.sort not in {"relevance", "hot", "top", "new", "comments"}
        or query.time_filter not in {"hour", "day", "week", "month", "year", "all"}
        or len(query.query) > 500
    ):
        raise ValueError("Invalid planned subreddit, query, sort or time window")
    return (
        "https://www.reddit.com/r/"
        + query.subreddit
        + "/search.json?"
        + urlencode(
            {
                "restrict_sr": "on",
                "q": query.query,
                "sort": query.sort,
                "t": query.time_filter,
                "limit": limit,
                "raw_json": 1,
            }
        )
    )


def acquire_public_json(
    session: Session, *, project_id: int, queries, budget: RunBudget, max_queries: int = 3
) -> AcquisitionResult:
    repository = RedditCollectionRepository(session)
    project = repository.get_project_by_project_id(project_id)
    before = repository.project_source_ids(project.id)
    selected = list(queries)[:max_queries]
    # Validate every selected query before a source call or write.
    for query in selected:
        search_url(query, 1)
    run = repository.start_collection_run(
        project.id,
        {
            "source": "public-json",
            "max_queries": max_queries,
            "max_items": budget.max_items,
            "max_requests": budget.max_requests,
        },
    )
    imported, seen, discussions = [], {"reddit_post": set(), "reddit_comment": set()}, set()
    status, reason = "completed", None
    session.commit()

    def fetch_import(url, query):
        budget.source_request()
        request = repository.create_request_log(
            project_db_id=project.id,
            run_id=run.id,
            endpoint=urlsplit_path(url),
            action="public_json",
            subreddit=query.subreddit,
            query=query.query,
            request_params={"url": url},
        )
        session.commit()
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "reddit-market-intel/0.1 (bounded read-only research)"},
                timeout=budget.timeout(30),
                allow_redirects=False,
            )
            repository.finish_request_log(
                request.id,
                status_code=response.status_code,
                response_headers=dict(response.headers),
            )
            if response.status_code in {403, 429}:
                raise PermissionError(f"Reddit access stopped: HTTP {response.status_code}")
            if (
                response.status_code != 200
                or "application/json" not in response.headers.get("Content-Type", "").lower()
            ):
                raise ValueError("Reddit returned non-JSON, verification or failed response")
            payload = response.json()
            with TemporaryDirectory(prefix="reddit-source-") as directory:
                path = Path(directory) / "response.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                options = dict(
                    project_id=project_id,
                    input_path=path,
                    acquisition_method="web_json",
                    source_url=url,
                    query=query.query,
                    sort=query.sort,
                    time_window=query.time_filter,
                    captured_at=datetime.now(UTC).isoformat(),
                )
                preview = import_reddit_export(session, **options, dry_run=True)
                returned = {
                    "reddit_post": {item["id"] for item in preview.items if item["type"] == "post"},
                    "reddit_comment": {
                        item["id"] for item in preview.items if item["type"] == "comment"
                    },
                }
                if sum(len(seen[k] | returned[k]) for k in seen) > budget.max_items:
                    raise BudgetExceeded("Source item budget exceeded by returned JSON")
                summary = import_reddit_export(session, **options)
                imported.append(summary.run_id)
                for kind in seen:
                    seen[kind].update(returned[kind])
                session.commit()
                return returned["reddit_post"]
        except Exception as exc:
            repository.finish_request_log(request.id, error=type(exc).__name__)
            session.commit()
            raise

    try:
        for query in selected:
            budget.check()
            remaining = budget.max_items - sum(map(len, seen.values()))
            if remaining <= 0:
                break
            found = fetch_import(
                search_url(query, max(1, min(remaining, budget.max_items // (max_queries + 1)))),
                query,
            )
            for post_id in sorted(found - discussions):
                remaining = budget.max_items - sum(map(len, seen.values()))
                if remaining <= 0:
                    break
                discussions.add(post_id)
                fetch_import(
                    f"https://www.reddit.com/comments/{post_id}.json?limit={remaining}&raw_json=1",
                    query,
                )
    except PermissionError as exc:
        status, reason = "blocked", str(exc)
    except BudgetExceeded as exc:
        status, reason = "blocked", str(exc)
    except Exception as exc:
        status, reason = "failed", f"Public JSON acquisition failed ({type(exc).__name__})"
    after = repository.project_source_ids(project.id)
    scope = {kind: sorted(after[kind] - before[kind]) for kind in before}
    if status == "completed" and not any(scope.values()):
        status, reason = "no_evidence", "No newly associated evidence for this project"
    run.status = status
    run.completed_at = datetime.now(UTC)
    run.summary = {
        "scope": scope,
        "repeat_ids": {kind: sorted(seen[kind] & before[kind]) for kind in before},
        "import_run_ids": imported,
        "source_requests": budget.requests,
        "reason": reason,
    }
    session.commit()
    return AcquisitionResult(status, run.id, scope, reason)


def urlsplit_path(url):
    from urllib.parse import urlsplit

    return urlsplit(url).path
