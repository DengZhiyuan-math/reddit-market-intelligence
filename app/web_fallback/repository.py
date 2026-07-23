"""Persistence helpers for public-web fallback ingestion."""

from datetime import UTC, datetime

from sqlalchemy import select
from app.db.models import DiscoveredUrlRecord, WebFallbackFetchRecord
from app.reddit.repository import RedditCollectionRepository
from app.web_fallback.models import FetchResult, PARSER_VERSION


class WebFallbackRepository(RedditCollectionRepository):
    """Repository for fallback URL candidates and fetch provenance."""

    def list_discovered_urls(self, project_db_id: int, limit: int) -> list[DiscoveredUrlRecord]:
        statement = (
            select(DiscoveredUrlRecord)
            .where(
                DiscoveredUrlRecord.project_id == project_db_id,
                DiscoveredUrlRecord.status == "discovered",
            )
            .order_by(DiscoveredUrlRecord.id)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def create_fetch_record(
        self,
        *,
        project_db_id: int,
        discovered_url_id: int | None,
        fetch: FetchResult,
        content_available: bool,
        risk_flags: list[str],
        metadata: dict,
    ) -> WebFallbackFetchRecord:
        record = WebFallbackFetchRecord(
            project_id=project_db_id,
            discovered_url_id=discovered_url_id,
            acquisition_method=fetch.acquisition_method,
            url=fetch.url,
            final_url=fetch.final_url,
            http_status=fetch.status_code,
            parser_version=PARSER_VERSION,
            content_available=content_available,
            risk_flags=risk_flags,
            error=fetch.error,
            metadata_json=metadata,
            fetched_at=datetime.now(UTC),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def mark_discovered_url(self, discovered_url_id: int, status: str) -> None:
        record = self.session.get(DiscoveredUrlRecord, discovered_url_id)
        if record is not None:
            record.status = status
            self.session.flush()
