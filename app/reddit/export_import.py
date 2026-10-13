"""Import already acquired Reddit exports. This module performs no network I/O."""

import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ProjectRedditPostRecord,
    ProjectRedditCommentRecord,
    RedditCommentRawRecord,
)

from app.reddit.models import ExportImportSummary, RedditCommentSnapshot, RedditPostSnapshot
from app.reddit.repository import RedditCollectionRepository

ROW_COLUMNS = {
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
}


def _id(value, kind, field):
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected a base36 Reddit ID")
    value = value.lower()
    if value.startswith("t") and "_" in value:
        if not value.startswith(kind + "_"):
            raise ValueError(f"{field}: expected {kind}_ fullname")
        value = value[len(kind) + 1 :]
    if not re.fullmatch(r"[a-z0-9]+", value):
        raise ValueError(f"{field}: expected a base36 Reddit ID")
    return value


def _number(value, field, nonnegative=False):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not re.fullmatch(r"-?\d+(?:\.0+)?", str(value)):
        raise ValueError(f"{field}: expected an integer or empty value")
    result = int(float(value)) if "." in str(value) else int(value)
    if abs(result) > 2**63 - 1 or (nonnegative and result < 0):
        raise ValueError(f"{field}: integer outside permitted range")
    return result


def _text(value, field):
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field}: expected text or null")
    return value


def _url(value, post_id=None, comment_id=None):
    if value in (None, ""):
        return None
    _text(value, "URL")
    if value.startswith("/") and not value.startswith("//"):
        value = "https://www.reddit.com" + value
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname
        not in {
            "reddit.com",
            "www.reddit.com",
            "old.reddit.com",
            "new.reddit.com",
            "np.reddit.com",
            "m.reddit.com",
            "redd.it",
        }
        or parsed.username
        or parsed.password
        or parsed.port
    ):
        raise ValueError("URL: expected an HTTPS Reddit source URL without credentials or port")
    if re.search(r"[\s<>\\]", value):
        raise ValueError("URL: invalid source URL characters")
    if post_id:
        if parsed.hostname == "redd.it":
            url_post, url_comment = parsed.path.strip("/").removesuffix(".json"), None
        else:
            match = re.fullmatch(
                r"/(?:r/[^/]+/)?comments/([a-zA-Z0-9]+)(?:/[^/]+)?(?:/([a-zA-Z0-9]+))?/?",
                parsed.path.removesuffix(".json"),
            )
            if not match:
                raise ValueError(
                    "URL: evidence must identify the actual Reddit discussion or comment"
                )
            url_post, url_comment = match.groups()
        if (
            _id(url_post, "t3", "URL post id") != post_id
            or url_comment
            and _id(url_comment, "t1", "URL comment id") != comment_id
        ):
            raise ValueError("URL: source post/comment ID does not match record")
    return value


def _parent(value, post_id, expected=None):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.lower().startswith(("t1_", "t3_")):
        raise ValueError("parent_id: expected t1_ or t3_ fullname")
    kind = value[:2].lower()
    parent = f"{kind}_{_id(value, kind, 'parent_id')}"
    if kind == "t3" and parent != f"t3_{post_id}" or expected and parent != expected:
        raise ValueError("parent_id: does not match post or nested reply parent")
    return parent


def _parse_rows(rows, method, posts, comments, summary, csv_input=False):
    for index, source in enumerate(rows, 1):
        if not isinstance(source, dict) or not ROW_COLUMNS.issubset(source):
            raise ValueError(f"Row {index}: required columns are {', '.join(sorted(ROW_COLUMNS))}")
        if None in source or any(value is None for value in source.values()) and csv_input:
            raise ValueError(f"Row {index}: CSV row has missing or extra cells")
        raw = dict(source)
        normalized = []
        for key, value in raw.items():
            if csv_input and isinstance(value, str) and re.match(r"'\s*[=+@-]", value):
                raw[key] = value[1:]
                normalized.append(key)
        if normalized:
            summary.warnings.append(
                f"Row {index}: removed author CSV formula-neutralization prefix from {', '.join(normalized)}; original row retained."
            )
        kind = raw["type"]
        if not isinstance(kind, str) or kind not in {"post", "comment"}:
            raise ValueError(f"Row {index} type: expected post or comment")
        rid = _id(raw["id"], "t3" if kind == "post" else "t1", f"Row {index} id")
        pid = _id(raw["post_id"], "t3", f"Row {index} post_id")
        if kind == "post" and rid != pid:
            raise ValueError(f"Row {index} post_id: does not match post id")
        url = _url(raw["source_url"], pid, rid if kind == "comment" else None)
        snapshot = {
            "source_snapshot": source,
            "acquisition_method": method,
            "normalized_fields": normalized,
        }
        for key in ("subreddit", "title", "text", "parent_id"):
            _text(raw.get(key), f"Row {index} {key}")
        fields = dict(
            body=raw["text"] if raw["text"] != "" else None,
            score=_number(raw["score"], f"Row {index} score"),
            created_utc=_number(raw["created_utc"], f"Row {index} created_utc", True),
            permalink=url,
            raw_json=snapshot,
        )
        coverage = summary.post_coverage.setdefault(
            pid,
            {
                "captured_comments": 0,
                "source_num_comments": None,
                "comments_complete": "unknown",
                "more_markers": 0,
                "known_omitted_count": 0,
            },
        )
        if kind == "post":
            count = _number(raw["num_comments"], f"Row {index} num_comments", True)
            coverage["source_num_comments"] = count
            posts.append(
                RedditPostSnapshot(
                    reddit_post_id=rid,
                    reddit_fullname=f"t3_{rid}",
                    subreddit=raw["subreddit"] or None,
                    title=raw["title"] or None,
                    num_comments=count,
                    **fields,
                )
            )
        else:
            comments.append(
                RedditCommentSnapshot(
                    reddit_comment_id=rid,
                    reddit_fullname=f"t1_{rid}",
                    reddit_post_id=pid,
                    parent_id=_parent(raw.get("parent_id"), pid),
                    depth=None,
                    **fields,
                )
            )
            coverage["captured_comments"] += 1


def _parse_listing(
    payload, method, posts, comments, summary, post_id=None, parent_id=None, depth=0
):
    if not isinstance(payload, dict) or payload.get("kind") != "Listing":
        raise ValueError(
            "Expected a Reddit Listing with data.children; HTML/login/error responses are not exports"
        )
    if not isinstance(payload.get("data"), dict):
        raise ValueError("Listing data must be an object")
    children = payload["data"].get("children")
    if not isinstance(children, list):
        raise ValueError("Listing data.children must be an array")
    for index, child in enumerate(children, 1):
        if not isinstance(child, dict) or not isinstance(child.get("data"), dict):
            raise ValueError(f"Listing child {index}: expected kind and data object")
        kind, raw = child.get("kind"), child["data"]
        if not isinstance(kind, str):
            raise ValueError(f"Listing child {index}: kind must be a string")
        if kind == "t3":
            pid = _id(raw.get("id"), "t3", f"Listing child {index} id")
            if raw.get("name") is not None and _id(raw["name"], "t3", "name") != pid:
                raise ValueError(f"Listing child {index} name: does not match id")
            for field in ("subreddit", "title", "selftext", "author", "url"):
                _text(raw.get(field), f"Listing child {index} {field}")
            url = _url(raw.get("permalink"), pid)
            posts.append(
                RedditPostSnapshot(
                    reddit_post_id=pid,
                    reddit_fullname=f"t3_{pid}",
                    subreddit=raw.get("subreddit"),
                    title=raw.get("title"),
                    body=raw.get("selftext"),
                    author=raw.get("author"),
                    score=_number(raw.get("score"), "score"),
                    num_comments=_number(raw.get("num_comments"), "num_comments", True),
                    created_utc=_number(raw.get("created_utc"), "created_utc", True),
                    permalink=url,
                    url=raw.get("url"),
                    raw_json={"source_snapshot": raw, "acquisition_method": method},
                )
            )
            summary.post_coverage.setdefault(
                pid,
                {
                    "captured_comments": 0,
                    "source_num_comments": raw.get("num_comments"),
                    "comments_complete": "unknown",
                    "more_markers": 0,
                    "known_omitted_count": 0,
                },
            )
        elif kind in {"t1", "more"}:
            pid = _id(raw["link_id"], "t3", "link_id") if raw.get("link_id") else post_id
            if not pid:
                raise ValueError(f"Listing child {index}: missing comment link_id/post context")
            if post_id and pid != post_id:
                raise ValueError("link_id: does not match Listing post context")
            parent = _parent(raw.get("parent_id"), pid, parent_id)
            coverage = summary.post_coverage.setdefault(
                pid,
                {
                    "captured_comments": 0,
                    "source_num_comments": None,
                    "comments_complete": "unknown",
                    "more_markers": 0,
                    "known_omitted_count": 0,
                },
            )
            if kind == "more":
                count = _number(raw.get("count"), "more count", True)
                if "children" in raw and not isinstance(raw["children"], list):
                    raise ValueError("more children must be a list")
                for missing in raw.get("children", []):
                    _id(missing, "t1", "more children id")
                summary.more_markers.append({"post_id": pid, **raw})
                coverage["comments_complete"] = "incomplete"
                coverage["more_markers"] += 1
                coverage["known_omitted_count"] += count or 0
                continue
            cid = _id(raw.get("id"), "t1", f"Listing child {index} id")
            if raw.get("name") is not None and _id(raw["name"], "t1", "name") != cid:
                raise ValueError(f"Listing child {index} name: does not match id")
            for field in ("body", "author"):
                _text(raw.get(field), f"Listing child {index} {field}")
            url = _url(raw.get("permalink"), pid, cid)
            comments.append(
                RedditCommentSnapshot(
                    reddit_comment_id=cid,
                    reddit_fullname=f"t1_{cid}",
                    reddit_post_id=pid,
                    parent_id=parent,
                    body=raw.get("body"),
                    author=raw.get("author"),
                    score=_number(raw.get("score"), "score"),
                    depth=depth,
                    created_utc=_number(raw.get("created_utc"), "created_utc", True),
                    permalink=url,
                    raw_json={"source_snapshot": raw, "acquisition_method": method},
                )
            )
            coverage["captured_comments"] += 1
            summary.nested_replies += depth > 0
            if raw.get("replies"):
                _parse_listing(
                    raw["replies"], method, posts, comments, summary, pid, f"t1_{cid}", depth + 1
                )
        else:
            raise ValueError(f"Listing child {index}: unsupported kind {kind!r}")


def import_reddit_export(
    session: Session,
    *,
    project_id: int,
    input_path: Path,
    acquisition_method: str,
    source_url: str | None = None,
    query: str | None = None,
    sort: str | None = None,
    time_window: str | None = None,
    captured_at: str | None = None,
    dry_run: bool = False,
) -> ExportImportSummary:
    """Validate a complete saved file, then atomically add project evidence."""
    if acquisition_method not in {"web_json", "manual_web", "dom"}:
        raise ValueError("acquisition_method must be web_json, manual_web, or dom")
    source_url = _url(source_url)
    if captured_at is not None:
        try:
            stamp = datetime.fromisoformat(captured_at)
            if stamp.tzinfo is None:
                raise ValueError("timezone is required")
            captured_at = stamp.astimezone(UTC).isoformat()
        except ValueError as exc:
            raise ValueError("captured_at: expected ISO 8601 timestamp with UTC offset") from exc
    data = input_path.read_bytes()
    text = data.decode("utf-8-sig")
    csv_input = input_path.suffix.lower() == ".csv"
    if csv_input:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if not ROW_COLUMNS.issubset(reader.fieldnames or []):
            raise ValueError("CSV header is missing required columns")
        payload = list(reader)
    else:
        payload = json.loads(text)
    posts, comments = [], []
    summary = ExportImportSummary(dry_run=dry_run)
    row_input = (
        csv_input
        or isinstance(payload, list)
        and (not payload or isinstance(payload[0], dict) and "type" in payload[0])
    )
    if row_input:
        _parse_rows(payload, acquisition_method, posts, comments, summary, csv_input)
    else:
        listings = payload if isinstance(payload, list) else [payload]
        for item in listings:
            context = posts[0].reddit_post_id if len(posts) == 1 else None
            _parse_listing(item, acquisition_method, posts, comments, summary, context)
    unique_posts, unique_comments = {}, {}
    for snapshots, unique, id_field in (
        (posts, unique_posts, "reddit_post_id"),
        (comments, unique_comments, "reddit_comment_id"),
    ):
        for snapshot in snapshots:
            rid = getattr(snapshot, id_field)
            if rid in unique:
                if snapshot.model_dump(exclude={"raw_json"}) != unique[rid].model_dump(
                    exclude={"raw_json"}
                ):
                    raise ValueError(
                        f"Conflicting duplicate id {rid}: records disagree within the file"
                    )
                summary.in_file_duplicates += 1
            else:
                unique[rid] = snapshot
    posts, comments = list(unique_posts.values()), list(unique_comments.values())
    with session.no_autoflush:
        for comment in comments:
            existing = session.scalar(
                select(RedditCommentRawRecord).where(
                    RedditCommentRawRecord.reddit_comment_id == comment.reddit_comment_id
                )
            )
            if existing and existing.reddit_post_id != comment.reddit_post_id:
                raise ValueError(
                    f"Comment {comment.reddit_comment_id} link_id: disagrees with stored post ID"
                )
            if comment.parent_id and comment.parent_id.startswith("t1_"):
                parent = unique_comments.get(comment.parent_id[3:]) or session.scalar(
                    select(RedditCommentRawRecord).where(
                        RedditCommentRawRecord.reddit_comment_id == comment.parent_id[3:]
                    )
                )
                if parent and parent.reddit_post_id != comment.reddit_post_id:
                    raise ValueError(
                        f"Comment {comment.reddit_comment_id} parent_id: parent belongs to another post"
                    )
    summary.captured_posts = len(posts)
    summary.captured_comments = len(comments)
    summary.nested_replies = sum((item.depth or 0) > 0 for item in comments)
    for coverage in summary.post_coverage.values():
        coverage["captured_comments"] = 0
    for comment in comments:
        summary.post_coverage[comment.reddit_post_id]["captured_comments"] += 1
    summary.items = [
        dict(
            type="post",
            id=item.reddit_post_id,
            post_id=item.reddit_post_id,
            source_url=item.permalink,
        )
        for item in posts
    ]
    summary.items.extend(
        dict(
            type="comment",
            id=item.reddit_comment_id,
            post_id=item.reddit_post_id,
            source_url=item.permalink,
        )
        for item in comments
    )
    for snapshot in [*posts, *comments]:
        for field in ("body", "author", "created_utc", "permalink"):
            if getattr(snapshot, field) in (None, ""):
                key = "text" if field == "body" else field
                summary.missing_fields[key] = summary.missing_fields.get(key, 0) + 1
        if isinstance(snapshot, RedditCommentSnapshot):
            for field in ("parent_id", "depth"):
                if getattr(snapshot, field) is None:
                    summary.missing_fields[field] = summary.missing_fields.get(field, 0) + 1
    summary.warnings.extend(
        f"Post {pid}: comments {coverage['comments_complete']}; captured {coverage['captured_comments']}, not source num_comments."
        for pid, coverage in summary.post_coverage.items()
    )
    if not posts and not comments:
        summary.warnings.append("Export is empty: no returned post or comment evidence.")
    if summary.missing_fields:
        summary.warnings.append(
            f"Missing fields: {summary.missing_fields}; missing text is not evidence."
        )
    config = dict(
        source_mode=acquisition_method,
        acquisition_method=acquisition_method,
        file_sha256=hashlib.sha256(data).hexdigest(),
        filename=input_path.name,
        source_url=source_url,
        query=query,
        sort=sort,
        time_window=time_window,
        captured_at=captured_at,
        imported_at=datetime.now(UTC).isoformat(),
        input_format="csv" if csv_input else "rows_json" if row_input else "listing_json",
        source_snapshot=payload,
    )
    repository = RedditCollectionRepository(session)
    if dry_run:
        return summary
    with session.begin_nested():
        project = repository.get_project_by_project_id(project_id)
        run = repository.start_collection_run(project.id, config)
        summary.run_id = run.id
        for snapshot in posts:
            raw, stored = repository.upsert_raw_post(snapshot)
            existing_link = session.scalar(
                select(ProjectRedditPostRecord).where(
                    ProjectRedditPostRecord.project_id == project.id,
                    ProjectRedditPostRecord.reddit_post_raw_id == raw.id,
                )
            )
            linked = False
            if existing_link is None:
                _, linked = repository.link_project_post_without_query(
                    project_db_id=project.id,
                    run_id=run.id,
                    raw_post=raw,
                    subreddit=snapshot.subreddit,
                    query=query,
                    sort=sort,
                    time_filter=time_window,
                    filters_json={
                        "acquisition_method": acquisition_method,
                        "source_url": snapshot.permalink,
                        "source_snapshot": snapshot.model_dump(mode="json", exclude={"raw_json"}),
                    },
                )
            summary.stored_posts += stored
            summary.duplicate_posts += not stored
            summary.new_post_links += linked
        for snapshot in comments:
            raw, stored = repository.upsert_raw_comment(snapshot)
            existing_link = session.scalar(
                select(ProjectRedditCommentRecord).where(
                    ProjectRedditCommentRecord.project_id == project.id,
                    ProjectRedditCommentRecord.reddit_comment_raw_id == raw.id,
                )
            )
            linked = False
            if existing_link is None:
                _, linked = repository.link_project_comment(
                    project_db_id=project.id,
                    run_id=run.id,
                    raw_comment=raw,
                    search_query_id=None,
                    request_id=None,
                    discovery_query=query,
                    sort=sort,
                    time_filter=time_window,
                    filters_json={
                        "acquisition_method": acquisition_method,
                        "source_url": snapshot.permalink,
                        "source_snapshot": snapshot.model_dump(mode="json", exclude={"raw_json"}),
                    },
                )
            summary.stored_comments += stored
            summary.duplicate_comments += not stored
            summary.new_comment_links += linked
        repository.complete_collection_run(run.id, "completed", summary)
    return summary
