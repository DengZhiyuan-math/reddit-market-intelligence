"""Read loaded DOM through an explicitly connected, task-owned browser tab."""

import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlencode
from uuid import uuid4

from app.config import Settings
from app.llm.transport import RunBudget

MAX_CAPTURE_CHARS = 200000


class BrowserDomError(RuntimeError):
    """Connected DOM access was blocked, invalid or unavailable."""


# Reads rendered DOM only. It deliberately excludes payload/state/network APIs.
DOM_SCRIPT = r"""(() => {
  const visible = el => !!el && !el.closest('[hidden],[aria-hidden="true"],[inert],[collapsed]') && el.getClientRects().length > 0;
  const escape = value => String(value ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const attrs = (el, keys) => keys.filter(key=>el.hasAttribute(key)).map(key=>' '+key+'="'+escape(el.getAttribute(key))+'"').join('');
  const main = document.querySelector('main');
  const text = (main || document.body).innerText || '';
  const barrier = /prove your humanity|verify you are human|you have been blocked|log in to continue|sign in to continue/i.test(document.title + '\n' + text.slice(0,3000));
  let html='<main>';
  for(const anchor of document.querySelectorAll('main h2 a[data-testid="post-title"]')) {
    if(visible(anchor))html+='<h2><a'+attrs(anchor,['href','data-testid'])+'></a></h2>';
  }
  for(const post of document.querySelectorAll('main shreddit-post')) {
    if(!visible(post))continue;
    html+='<shreddit-post'+attrs(post,['id','permalink','subreddit-name','post-title','score','comment-count','created-timestamp'])+'>';
    const body=post.querySelector('shreddit-post-text-body [property="schema:articleBody"]');
    if(visible(body))html+='<shreddit-post-text-body><div property="schema:articleBody">'+escape(body.innerText)+'</div></shreddit-post-text-body>';
    html+='</shreddit-post>';
  }
  for(const comment of document.querySelectorAll('main shreddit-comment')) {
    if(!visible(comment))continue;
    const body=Array.from(comment.querySelectorAll('div[slot="comment"]')).find(el=>el.closest('shreddit-comment')===comment);
    if(!visible(body))continue;
    const parent=comment.parentElement.closest('shreddit-comment');
    html+='<shreddit-comment'+attrs(comment,['thingid','postid','permalink','created','score','depth'])+(parent ? ' parentid="'+escape(parent.getAttribute('thingid'))+'"' : attrs(comment,['parentid']))+'>';
    const ownText = node => node.nodeType===3 ? (visible(node.parentElement) && node.parentElement.closest('shreddit-comment')===comment ? node.textContent : '') : node.nodeType===1 && visible(node) && node.closest('shreddit-comment')===comment ? Array.from(node.childNodes).map(ownText).join(node.matches('p,div,li') ? '\n' : '') : '';
    html+='<div slot="comment" id="'+escape(comment.getAttribute('thingid'))+'-comment-rtjson-content">'+escape(ownText(body))+'</div></shreddit-comment>';
  }
  if(!html.includes('<h2>') && /no results|couldn.t find any results/i.test(text))html+='No results';
  return {html:html+'</main>',barrier};
})()"""


def validate_browser_config(settings):
    parsed = urlsplit(settings.browser_dom_cdp_url or "")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BrowserDomError("Connected browser requires an explicit loopback CDP URL with port")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", settings.browser_dom_session):
        raise BrowserDomError("Invalid task browser session name")


class ConnectedBrowser:
    def __init__(self, settings: Settings, budget: RunBudget):
        validate_browser_config(settings)
        self.settings, self.budget = settings, budget
        self.directory = TemporaryDirectory(prefix="reddit-dom-")
        self.config = Path(self.directory.name) / "agent-browser.json"
        self.config.write_text("{}", encoding="utf-8")
        self.label = "reddit-capture-" + uuid4().hex[:10]

    def __enter__(self):
        try:
            self.command(["connect", self.settings.browser_dom_cdp_url])
            self.command(["tab", "new", "--label", self.label])
        except Exception:
            self.directory.cleanup()
            raise
        return self

    def __exit__(self, *args):
        # Leave the labeled tab for root inspection. Never shut down a browser.
        self.directory.cleanup()

    def command(self, command, *, script=None, navigation=False):
        self.budget.browser_operation(navigation=navigation)
        args = [
            self.settings.browser_dom_executable,
            "--config",
            str(self.config),
            "--session",
            self.settings.browser_dom_session,
            "--cdp",
            self.settings.browser_dom_cdp_url,
            "--json",
            "--max-output",
            str(MAX_CAPTURE_CHARS),
            *command,
        ]
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AGENT_BROWSER_")
            and key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
        }
        env["AGENT_BROWSER_DEFAULT_TIMEOUT"] = str(
            int(self.budget.timeout(self.settings.browser_dom_timeout_seconds) * 1000)
        )
        try:
            result = subprocess.run(
                args,
                input=script,
                shell=False,
                cwd=self.directory.name,
                env=env,
                text=True,
                capture_output=True,
                timeout=self.budget.timeout(self.settings.browser_dom_timeout_seconds),
            )
            if (
                result.returncode
                or len(result.stdout) > MAX_CAPTURE_CHARS
                or len(result.stderr) > MAX_CAPTURE_CHARS
            ):
                raise BrowserDomError("Connected browser command failed or exceeded output limit")
            payload = json.loads(result.stdout)
            if payload.get("success") is not True:
                raise BrowserDomError("Connected browser returned an unsuccessful command")
            lifecycle = payload.get("data", {}).get("lifecycle", {})
            if (
                lifecycle.get("launched")
                and not (command[0] == "connect" and lifecycle.get("reused") is True)
                or lifecycle.get("relaunchedBrowser")
                or lifecycle.get("restoreStatus") not in {None, "not_configured"}
            ):
                raise BrowserDomError("Browser command unexpectedly launched or restored a session")
            return payload["data"]
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
            raise BrowserDomError(f"Connected browser unavailable ({type(exc).__name__})") from None

    def capture(self, url):
        self.command(["tab", self.label])
        self.command(["open", url], navigation=True)
        self.command(["wait", "--load", "domcontentloaded"])
        title = self.command(["get", "title"])["title"]
        final_url = self.command(["get", "url"])["url"]
        _reddit_url(final_url)
        if re.search(r"prove your humanity|verify you are human|log in to continue", title, re.I):
            raise PermissionError("Reddit DOM blocked by verification or login")
        requested_path = urlsplit(url).path.rstrip("/")
        if requested_path.endswith("/search"):
            if urlsplit(final_url).path.rstrip("/") != requested_path:
                raise BrowserDomError("Unexpected search redirect")
        elif _discussion_id(url) != _discussion_id(final_url):
            raise BrowserDomError("Unexpected discussion redirect")
        self.command(["snapshot", "-c", "-d", "3", "-s", "main"])
        result = self.command(["eval", "--stdin"], script=DOM_SCRIPT)["result"]
        if (
            not isinstance(result, dict)
            or set(result) != {"html", "barrier"}
            or not isinstance(result["html"], str)
            or type(result["barrier"]) is not bool
        ):
            raise BrowserDomError("Malformed DOM capture")
        return {**result, "title": title, "url": final_url, "tab_label": self.label}


def _reddit_url(value):
    from urllib.parse import urljoin

    url = urljoin("https://www.reddit.com", value)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.reddit.com", "reddit.com"}
        or parsed.username
        or parsed.password
        or parsed.port
        or re.search(r"[\s<>\\]", url)
    ):
        raise BrowserDomError("Invalid Reddit DOM source URL")
    return url


def _discussion_id(url):
    parsed = urlsplit(_reddit_url(url))
    match = re.fullmatch(r"/r/[A-Za-z0-9_]{2,21}/comments/([a-z0-9]+)/(?:[^/]+/)?", parsed.path)
    if not match:
        raise BrowserDomError("Unsupported or redirected discussion URL")
    return match.group(1)


def _page(capture, *, search=False, expected_post_id=None):
    from bs4 import BeautifulSoup

    if (
        not isinstance(capture, dict)
        or not isinstance(capture.get("html"), str)
        or len(capture["html"]) > MAX_CAPTURE_CHARS
    ):
        raise BrowserDomError("Malformed or oversized DOM capture")
    url = _reddit_url(capture.get("url") or "")
    parsed = urlsplit(url)
    soup = BeautifulSoup(capture["html"], "html.parser")
    barrier_text = (capture.get("title", "") + " " + soup.get_text(" ", strip=True)[:3000]).lower()
    if capture.get("barrier") or re.search(
        r"prove your humanity|verify you are human|you have been blocked|log in to continue|sign in to continue",
        barrier_text,
    ):
        raise PermissionError("Reddit DOM blocked by verification or login")
    if search:
        if not re.fullmatch(r"/r/[A-Za-z0-9_]{2,21}/search/?", parsed.path):
            raise BrowserDomError("Unsupported or redirected search URL")
    elif _discussion_id(url) != expected_post_id:
        raise BrowserDomError("Discussion identity does not match candidate")
    return soup


def _shown(node):
    if node is None:
        return False
    for item in [node, *node.parents]:
        if (
            getattr(item, "attrs", {}).get("aria-hidden") == "true"
            or any(key in getattr(item, "attrs", {}) for key in ("hidden", "inert", "collapsed"))
            or re.search(
                r"display\s*:\s*none|visibility\s*:\s*hidden",
                getattr(item, "attrs", {}).get("style", ""),
            )
        ):
            return False
    return True


def parse_search_capture(capture):
    soup = _page(capture, search=True)
    main = soup.select_one("main")
    if main is None:
        raise BrowserDomError("unsupported_structure: search main missing")
    links = []
    seen = set()
    anchors = main.select('h2 a[data-testid="post-title"]')
    if not anchors and not re.search(
        r"no results|couldn.t find any results", main.get_text(" ", strip=True), re.I
    ):
        raise BrowserDomError("unsupported_structure: search result mapping missing")
    for anchor in anchors:
        if not _shown(anchor):
            continue
        url = _reddit_url(anchor.get("href") or "")
        rid = _discussion_id(url)
        if rid not in seen:
            links.append(url)
            seen.add(rid)
    return links


def _canonical(value, kind):
    if not isinstance(value, str) or not re.fullmatch(kind + r"_[a-z0-9]+", value):
        raise BrowserDomError("Malformed canonical DOM ID")
    return value[3:]


def _integer(value, field):
    if value in (None, ""):
        return None
    if not re.fullmatch(r"-?\d+", str(value)):
        raise BrowserDomError("Invalid DOM numeric field " + field)
    return int(value)


def _created(value):
    from datetime import datetime

    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError("timezone missing")
        return int(stamp.timestamp())
    except ValueError:
        raise BrowserDomError("Invalid observed DOM timestamp") from None


def parse_discussion_capture(capture, *, expected_post_id):
    from app.reddit.export_import import _url

    soup = _page(capture, expected_post_id=expected_post_id)
    posts = [node for node in soup.select("main shreddit-post") if _shown(node)]
    if len(posts) != 1:
        raise BrowserDomError("unsupported_structure: exactly one original post required")
    post = posts[0]
    pid = _canonical(post.get("id"), "t3")
    if pid != expected_post_id:
        raise BrowserDomError("Post ID disagrees with navigated discussion")
    url = _url(post.get("permalink"), pid)
    if not url:
        raise BrowserDomError("Original post permalink missing")
    body = post.select_one('shreddit-post-text-body [property="schema:articleBody"]')
    # Missing originals stay unknown; never substitute whole-page/meta/title text.
    text = body.get_text("\n", strip=True) if _shown(body) else None
    row = dict(
        type="post",
        id=pid,
        post_id=pid,
        subreddit=post.get("subreddit-name"),
        title=post.get("post-title"),
        text=text,
        created_utc=_created(post.get("created-timestamp")),
        score=_integer(post.get("score"), "score"),
        num_comments=_integer(post.get("comment-count"), "comment-count"),
        source_url=url,
        parent_id=None,
    )
    rows = [row]
    for comment in soup.select("main shreddit-comment"):
        if not _shown(comment):
            continue
        cid = _canonical(comment.get("thingid"), "t1")
        if _canonical(comment.get("postid"), "t3") != pid:
            raise BrowserDomError("Comment post ID mismatch")
        own = next(
            (
                node
                for node in comment.select('div[slot="comment"]')
                if node.find_parent("shreddit-comment") is comment
            ),
            None,
        )
        if not _shown(own):
            continue
        if own.get("id") != "t1_" + cid + "-comment-rtjson-content":
            raise BrowserDomError("unsupported_structure: own comment body identity missing")
        for nested in own.select('shreddit-comment,[hidden],[aria-hidden="true"],[collapsed]'):
            nested.decompose()
        parent = comment.get("parentid")
        nested_parent = comment.find_parent("shreddit-comment")
        if nested_parent is not None:
            observed = nested_parent.get("thingid")
            if parent and parent != observed:
                raise BrowserDomError("Observed comment parent conflict")
            parent = observed
        rows.append(
            dict(
                type="comment",
                id=cid,
                post_id=pid,
                subreddit=row["subreddit"],
                title=None,
                text=own.get_text("\n", strip=True) or None,
                created_utc=_created(comment.get("created")),
                score=_integer(comment.get("score"), "score"),
                num_comments=None,
                source_url=_url(comment.get("permalink"), pid, cid),
                parent_id=parent,
                observed_depth=_integer(comment.get("depth"), "depth"),
            )
        )
        if not rows[-1]["source_url"]:
            raise BrowserDomError("Original comment permalink missing")
    return rows


def acquire_browser_dom(
    session,
    *,
    project_id,
    queries,
    settings: Settings,
    budget: RunBudget,
    max_queries=3,
    output_dir: Path,
):
    """Automatically search and import only original loaded discussion records."""
    from datetime import UTC, datetime
    import hashlib
    from html import escape
    from app.reddit.export_import import import_reddit_export
    from app.reddit.public_json import AcquisitionResult, search_url
    from app.reddit.repository import RedditCollectionRepository

    validate_browser_config(settings)
    selected = list(queries)[:max_queries]
    search_urls = []
    for query in selected:
        api_url = search_url(query, 1)  # Existing subreddit/query/sort/time validation.
        parsed = urlsplit(api_url)
        search_urls.append(
            "https://www.reddit.com"
            + parsed.path.replace("search.json", "search/")
            + "?"
            + urlencode(
                {
                    "q": query.query,
                    "restrict_sr": "on",
                    "sort": query.sort,
                    "t": query.time_filter,
                    "type": "posts",
                }
            )
        )
    repository = RedditCollectionRepository(session)
    project = repository.get_project_by_project_id(project_id)
    before = repository.project_source_ids(project.id)
    run = repository.start_collection_run(
        project.id,
        {
            "source": "browser-dom",
            "extractor_version": "shreddit-own-body.v1",
            "max_items": budget.max_items,
            "max_navigations": budget.max_requests,
            "max_browser_operations": budget.max_browser_operations,
        },
    )
    session.commit()
    seen = {"reddit_post": set(), "reddit_comment": set()}
    captures, searches, visited = [], [], set()
    status, reason = "completed", None
    directory = Path(output_dir) / f"acquisition-{run.id}"
    try:
        with ConnectedBrowser(settings, budget) as browser:
            run.run_config = {**run.run_config, "tab_label": browser.label}
            for query, search in zip(selected, search_urls, strict=True):
                budget.check()
                capture = browser.capture(search)
                if urlsplit(capture["url"]).path.rstrip("/") != urlsplit(search).path.rstrip("/"):
                    raise BrowserDomError("Unexpected search redirect")
                candidates = parse_search_capture(capture)
                searches.append(
                    {
                        "source_url": capture["url"],
                        "query": query.query,
                        "sort": query.sort,
                        "time_window": query.time_filter,
                        "candidate_urls": candidates,
                    }
                )
                for url in candidates:
                    pid = _discussion_id(url)
                    if pid in visited:
                        continue
                    remaining = budget.max_items - sum(map(len, seen.values()))
                    if remaining <= 0:
                        break
                    visited.add(pid)
                    discussion = browser.capture(url)
                    rows = parse_discussion_capture(discussion, expected_post_id=pid)
                    returned = {
                        "reddit_post": {row["id"] for row in rows if row["type"] == "post"},
                        "reddit_comment": {row["id"] for row in rows if row["type"] == "comment"},
                    }
                    # A whole capture is accepted or rejected; no unvalidated partial write.
                    if sum(len(seen[kind] | returned[kind]) for kind in seen) > budget.max_items:
                        from app.llm.transport import BudgetExceeded

                        raise BudgetExceeded("Loaded DOM exceeds source item budget")
                    with TemporaryDirectory(prefix="reddit-dom-import-") as temp:
                        path = Path(temp) / "loaded-dom.json"
                        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                        options = dict(
                            project_id=project_id,
                            input_path=path,
                            acquisition_method="dom",
                            source_url=discussion["url"],
                            query=query.query,
                            sort=query.sort,
                            time_window=query.time_filter,
                            captured_at=datetime.now(UTC).isoformat(),
                        )
                        preview = import_reddit_export(session, **options, dry_run=True)
                        imported = import_reddit_export(session, **options)
                    # Save an evidence-only DOM projection; never retain whole-page account/ads/tracking dumps.
                    proof = (
                        '<main data-extractor="shreddit-own-body.v1">'
                        + "".join(
                            '<article data-type="'
                            + row["type"]
                            + '" data-id="'
                            + row["id"]
                            + '"><a href="'
                            + escape(row["source_url"], quote=True)
                            + '">'
                            + escape(row["id"])
                            + "</a><h2>"
                            + escape(row.get("title") or "")
                            + "</h2><p>"
                            + escape(row.get("text") or "")
                            + "</p></article>"
                            for row in rows
                        )
                        + "</main>"
                    )
                    directory.mkdir(parents=True, exist_ok=True)
                    artifact = directory / f"{pid}.html"
                    artifact.write_text(proof, encoding="utf-8")
                    metadata = {
                        "source_url": discussion["url"],
                        "captured_at": options["captured_at"],
                        "query": query.query,
                        "sort": query.sort,
                        "time_window": query.time_filter,
                        "extractor_version": "shreddit-own-body.v1",
                        "structure_status": "supported_observed_mapping",
                        "capture_dom_sha256": hashlib.sha256(proof.encode()).hexdigest(),
                        "artifact": str(artifact),
                        "import_run_id": imported.run_id,
                        "loaded_comments": preview.captured_comments,
                        "comments_complete": "unknown",
                        "missing_fields": preview.missing_fields,
                        "returned_ids": preview.items,
                        "tab_label": browser.label,
                        "projection": "normalized original-body DOM evidence only",
                    }
                    captures.append(metadata)
                    for kind in seen:
                        seen[kind].update(returned[kind])
                    imported_run = session.get(type(run), imported.run_id)
                    imported_run.run_config = {**imported_run.run_config, "dom_capture": metadata}
                    session.commit()
                if sum(map(len, seen.values())) >= budget.max_items:
                    break
    except (PermissionError,) as exc:
        status, reason = "blocked", str(exc)
    except Exception as exc:
        from app.llm.transport import BudgetExceeded

        status = "blocked" if isinstance(exc, BudgetExceeded) else "failed"
        reason = (
            str(exc)
            if isinstance(exc, (BrowserDomError, BudgetExceeded, ValueError))
            else f"DOM acquisition failed ({type(exc).__name__})"
        )
    after = repository.project_source_ids(project.id)
    scope = {kind: sorted(after[kind] - before[kind]) for kind in before}
    if status == "completed" and not any(scope.values()):
        status, reason = "no_evidence", "No newly associated loaded DOM evidence for this project"
    run.status = status
    run.completed_at = datetime.now(UTC)
    run.summary = {
        "scope": scope,
        "repeat_ids": {kind: sorted(seen[kind] & before[kind]) for kind in before},
        "searches": searches,
        "captures": captures,
        "browser_navigations": budget.browser_navigations,
        "browser_operations": budget.browser_operations,
        "internal_http_requests": None,
        "reason": reason,
    }
    session.commit()
    return AcquisitionResult(status, run.id, scope, reason)
