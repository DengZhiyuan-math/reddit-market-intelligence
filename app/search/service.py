"""Service orchestration for URL discovery."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.search.models import DiscoveryRunSummary
from app.search.provider import GoogleCustomSearchProvider
from app.search.repository import DiscoveryRepository


class DiscoveryServiceError(RuntimeError):
    """Raised when URL discovery cannot complete."""


def validate_search_settings(settings: Settings):
    """Validate configured search provider settings."""

    return GoogleCustomSearchProvider.validate_settings(settings)


def run_url_discovery(
    session: Session,
    *,
    project_id: int,
    query: str,
    limit: int,
    dry_run: bool,
    settings: Settings | None = None,
    provider: GoogleCustomSearchProvider | None = None,
) -> DiscoveryRunSummary:
    """Discover candidate URLs and optionally persist them."""

    resolved_settings = settings or Settings()
    resolved_provider = provider or GoogleCustomSearchProvider(resolved_settings)
    try:
        urls = resolved_provider.search(query, limit=limit)
    except Exception as exc:
        raise DiscoveryServiceError(str(exc)) from exc

    summary = DiscoveryRunSummary(
        provider=resolved_provider.provider_name,
        query=query,
        discovered=len(urls),
        dry_run=dry_run,
        urls=urls,
    )
    if dry_run:
        return summary

    repository = DiscoveryRepository(session)
    project = repository.get_project_by_project_id(project_id)
    stored, duplicates = repository.store_discovered_urls(
        project_db_id=project.id,
        provider=resolved_provider.provider_name,
        query=query,
        urls=urls,
    )
    summary.stored = stored
    summary.duplicates = duplicates
    return summary
