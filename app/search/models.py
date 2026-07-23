"""Models for search-based URL discovery."""

from pydantic import BaseModel, Field


class SearchProviderStatus(BaseModel):
    """Configuration validation result for a search provider."""

    valid: bool
    reason_codes: list[str] = Field(default_factory=list)
    message: str


class DiscoveredUrl(BaseModel):
    """One URL discovered by a search provider."""

    url: str
    title: str | None = None
    snippet: str | None = None
    metadata: dict = Field(default_factory=dict)


class DiscoveryRunSummary(BaseModel):
    """User-facing summary for one URL discovery run."""

    provider: str
    query: str
    discovered: int = 0
    stored: int = 0
    duplicates: int = 0
    dry_run: bool = False
    urls: list[DiscoveredUrl] = Field(default_factory=list)
