"""Persistence for search-discovered URLs."""

from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DiscoveredUrlRecord, ResearchProjectRecord
from app.search.models import DiscoveredUrl


class DiscoveryRepository:
    """Database access for discovered URL records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_project_by_project_id(self, project_id: int) -> ResearchProjectRecord:
        project = self.session.scalar(
            select(ResearchProjectRecord).where(ResearchProjectRecord.project_id == project_id)
        )
        if project is None:
            raise ValueError(f"Project not found in database: {project_id}")
        return project

    def store_discovered_urls(
        self,
        *,
        project_db_id: int,
        provider: str,
        query: str,
        urls: list[DiscoveredUrl],
    ) -> tuple[int, int]:
        stored = 0
        duplicates = 0
        for discovered in urls:
            normalized = normalize_url(discovered.url)
            existing = self.session.scalar(
                select(DiscoveredUrlRecord).where(
                    DiscoveredUrlRecord.project_id == project_db_id,
                    DiscoveredUrlRecord.provider == provider,
                    DiscoveredUrlRecord.normalized_url == normalized,
                )
            )
            if existing is not None:
                duplicates += 1
                continue
            self.session.add(
                DiscoveredUrlRecord(
                    project_id=project_db_id,
                    provider=provider,
                    query=query,
                    url=discovered.url,
                    normalized_url=normalized,
                    title=discovered.title,
                    snippet=discovered.snippet,
                    metadata_json=discovered.metadata,
                )
            )
            stored += 1
        return stored, duplicates


def normalize_url(url: str) -> str:
    """Normalize URL for deterministic deduplication."""

    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))
