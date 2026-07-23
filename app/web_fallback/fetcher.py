"""Fetchers for public-web fallback ingestion."""

from app.web_fallback.models import FetchResult


class RequestsStaticFetcher:
    """Static HTTP fetcher backed by requests."""

    acquisition_method = "web_static"

    def fetch(self, url: str) -> FetchResult:
        import requests

        try:
            response = requests.get(url, timeout=20)
        except requests.RequestException as exc:
            return FetchResult(url=url, error=str(exc), acquisition_method=self.acquisition_method)
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            text=response.text,
            acquisition_method=self.acquisition_method,
        )


class PlaywrightBrowserFetcher:
    """Optional browser-rendered fetcher backed by Playwright when installed."""

    acquisition_method = "web_browser"

    def fetch(self, url: str) -> FetchResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return FetchResult(
                url=url,
                error="Playwright is not installed. Install it only when browser fallback is needed.",
                acquisition_method=self.acquisition_method,
            )

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                text = page.content()
                final_url = page.url
                status_code = response.status if response is not None else None
                browser.close()
        except Exception as exc:
            return FetchResult(url=url, error=str(exc), acquisition_method=self.acquisition_method)
        return FetchResult(
            url=url,
            final_url=final_url,
            status_code=status_code,
            text=text,
            acquisition_method=self.acquisition_method,
        )
