"""Search provider integrations."""

import json
from urllib.parse import urlencode
from urllib.request import urlopen

from app.config import Settings
from app.search.models import DiscoveredUrl, SearchProviderStatus


class SearchProviderError(RuntimeError):
    """Raised when search discovery cannot run."""


class GoogleCustomSearchProvider:
    """Minimal Google Custom Search JSON API provider."""

    provider_name = "google_custom_search"
    endpoint = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def validate_settings(settings: Settings) -> SearchProviderStatus:
        reasons: list[str] = []
        if not settings.google_custom_search_api_key:
            reasons.append("missing_google_custom_search_api_key")
        if not settings.google_custom_search_engine_id:
            reasons.append("missing_google_custom_search_engine_id")
        if reasons:
            return SearchProviderStatus(
                valid=False,
                reason_codes=reasons,
                message="Google Custom Search settings are incomplete.",
            )
        return SearchProviderStatus(
            valid=True,
            reason_codes=[],
            message="Google Custom Search settings are configured.",
        )

    def search(self, query: str, *, limit: int) -> list[DiscoveredUrl]:
        status = self.validate_settings(self.settings)
        if not status.valid:
            raise SearchProviderError(status.message + " " + ", ".join(status.reason_codes))

        params = urlencode(
            {
                "key": self.settings.google_custom_search_api_key,
                "cx": self.settings.google_custom_search_engine_id,
                "q": query,
                "num": min(limit, 10),
            }
        )
        with urlopen(f"{self.endpoint}?{params}", timeout=20) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return parse_google_custom_search_results(payload, limit=limit)


def parse_google_custom_search_results(payload: dict, *, limit: int) -> list[DiscoveredUrl]:
    """Extract URL results from a Google Custom Search JSON payload."""

    results: list[DiscoveredUrl] = []
    for item in payload.get("items", [])[:limit]:
        link = item.get("link")
        if not link:
            continue
        results.append(
            DiscoveredUrl(
                url=link,
                title=item.get("title"),
                snippet=item.get("snippet"),
                metadata=item,
            )
        )
    return results
