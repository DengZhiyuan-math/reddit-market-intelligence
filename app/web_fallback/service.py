"""Service orchestration for public-web fallback ingestion."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.sources.selection import CollectionSourceMode, select_collection_source
from app.web_fallback.fetcher import PlaywrightBrowserFetcher, RequestsStaticFetcher
from app.web_fallback.models import WebFallbackIngestionSummary
from app.web_fallback.parser import parse_reddit_discussion_html
from app.web_fallback.repository import WebFallbackRepository


class WebFallbackServiceError(RuntimeError):
    """Raised when public-web fallback ingestion cannot run."""


def run_web_fallback_ingestion(
    session: Session,
    *,
    project_id: int,
    limit: int,
    settings: Settings | None = None,
    fetcher=None,
) -> WebFallbackIngestionSummary:
    """Fetch discovered URLs and ingest parseable public Reddit evidence."""

    resolved_settings = settings or Settings()
    selection = select_collection_source(resolved_settings)
    if selection.mode not in {
        CollectionSourceMode.WEB_FALLBACK_STATIC,
        CollectionSourceMode.WEB_FALLBACK_BROWSER,
    }:
        raise WebFallbackServiceError(selection.message + " " + ", ".join(selection.reason_codes))

    repository = WebFallbackRepository(session)
    project = repository.get_project_by_project_id(project_id)
    candidates = repository.list_discovered_urls(project.id, limit)
    resolved_fetcher = fetcher or _fetcher_for_mode(selection.mode)
    summary = WebFallbackIngestionSummary(candidates=len(candidates))
    run = repository.start_collection_run(
        project.id,
        {"source_mode": selection.mode.value, "limit": limit, "fallback": True},
    )

    for candidate in candidates:
        fetch = resolved_fetcher.fetch(candidate.url)
        summary.fetched += 1
        if fetch.error or not fetch.text or (fetch.status_code is not None and fetch.status_code >= 400):
            summary.errors += 1
            repository.create_fetch_record(
                project_db_id=project.id,
                discovered_url_id=candidate.id,
                fetch=fetch,
                content_available=False,
                risk_flags=selection.risk_flags,
                metadata={"reason": "fetch_failed"},
            )
            repository.mark_discovered_url(candidate.id, "fetch_failed")
            continue

        parsed = parse_reddit_discussion_html(fetch.text, url=fetch.final_url or candidate.url)
        fetch_record = repository.create_fetch_record(
            project_db_id=project.id,
            discovered_url_id=candidate.id,
            fetch=fetch,
            content_available=parsed.content_available,
            risk_flags=selection.risk_flags,
            metadata={"exclusion_reason": parsed.exclusion_reason},
        )
        if not parsed.content_available or parsed.post is None:
            summary.excluded += 1
            repository.mark_discovered_url(candidate.id, parsed.exclusion_reason or "excluded")
            continue

        parsed.post.raw_json.update(
            {
                "acquisition_method": fetch.acquisition_method,
                "web_fallback_fetch_id": fetch_record.id,
                "risk_flags": selection.risk_flags,
            }
        )
        raw_post, post_inserted = repository.upsert_raw_post(parsed.post)
        if post_inserted:
            summary.stored_posts += 1
        else:
            summary.duplicate_posts += 1
        repository.link_project_post_without_query(
            project_db_id=project.id,
            run_id=run.id,
            raw_post=raw_post,
            subreddit=parsed.post.subreddit,
            query=candidate.query,
            filters_json={"source": "web_fallback", "discovered_url_id": candidate.id},
        )

        for comment in parsed.comments:
            comment.raw_json.update(
                {
                    "acquisition_method": fetch.acquisition_method,
                    "web_fallback_fetch_id": fetch_record.id,
                    "risk_flags": selection.risk_flags,
                }
            )
            raw_comment, comment_inserted = repository.upsert_raw_comment(comment)
            if comment_inserted:
                summary.stored_comments += 1
            else:
                summary.duplicate_comments += 1
            repository.link_project_comment(
                project_db_id=project.id,
                run_id=run.id,
                search_query_id=None,
                request_id=None,
                raw_comment=raw_comment,
            )
        repository.mark_discovered_url(candidate.id, "ingested")

    repository.complete_collection_run(run.id, "completed", summary)  # type: ignore[arg-type]
    return summary


def _fetcher_for_mode(mode: CollectionSourceMode):
    if mode == CollectionSourceMode.WEB_FALLBACK_BROWSER:
        return PlaywrightBrowserFetcher()
    return RequestsStaticFetcher()
