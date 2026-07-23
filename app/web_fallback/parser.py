"""Parse public Reddit discussion HTML into raw snapshots."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.reddit.models import RedditCommentSnapshot, RedditPostSnapshot
from app.web_fallback.models import ParsedFallbackPage


POST_ID_RE = re.compile(r"/comments/([^/]+)/")
SUBREDDIT_RE = re.compile(r"/r/([^/]+)/")


def parse_reddit_discussion_html(html: str, *, url: str) -> ParsedFallbackPage:
    """Parse a limited public Reddit discussion page representation."""

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    title_text = (_text_or_none(soup.find("title")) or "").lower()
    if "please wait for verification" in title_text or "please wait for verification" in text:
        return ParsedFallbackPage(content_available=False, exclusion_reason="verification_required")
    if "[deleted]" in text or "[removed]" in text or "this content is no longer available" in text:
        return ParsedFallbackPage(content_available=False, exclusion_reason="deleted_or_removed")

    post_id = _extract_post_id(url)
    if not post_id:
        return ParsedFallbackPage(content_available=False, exclusion_reason="missing_post_id")

    title = _first_meta(soup, "og:title") or _text_or_none(soup.find("title"))
    body = _first_meta(soup, "description") or _text_or_none(
        soup.find(attrs={"data-reddit-post-body": True})
    )
    if not title and not body:
        return ParsedFallbackPage(content_available=False, exclusion_reason="empty_content")

    subreddit = _extract_subreddit(url)
    comments = []
    for node in soup.find_all(attrs={"data-reddit-comment-id": True}):
        comment_id = str(node.get("data-reddit-comment-id"))
        comment_body = _text_or_none(node)
        if not comment_body or comment_body.lower() in {"[deleted]", "[removed]"}:
            continue
        comments.append(
            RedditCommentSnapshot(
                reddit_comment_id=f"web_{comment_id}",
                reddit_fullname=None,
                reddit_post_id=f"web_{post_id}",
                parent_id=f"t3_web_{post_id}",
                body=comment_body,
                author=None,
                depth=0,
                permalink=url,
                raw_json={"source": "web_fallback", "original_comment_id": comment_id},
            )
        )

    post = RedditPostSnapshot(
        reddit_post_id=f"web_{post_id}",
        reddit_fullname=None,
        subreddit=subreddit,
        title=title,
        body=body,
        author=None,
        permalink=urlsplit(url).path,
        url=url,
        raw_json={"source": "web_fallback", "parser": "reddit-html-v1", "url": url},
    )
    return ParsedFallbackPage(post=post, comments=comments, content_available=True)


def _extract_post_id(url: str) -> str | None:
    match = POST_ID_RE.search(urlsplit(url).path)
    return match.group(1) if match else None


def _extract_subreddit(url: str) -> str | None:
    match = SUBREDDIT_RE.search(urlsplit(url).path)
    return match.group(1) if match else None


def _first_meta(soup: BeautifulSoup, name: str) -> str | None:
    node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    value = node.get("content") if node is not None else None
    return str(value).strip() if value else None


def _text_or_none(node) -> str | None:
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return text or None
